import asyncio
import time

import pytz
from sqlalchemy import inspect, select

from balancebot.api.database import session
from balancebot.api.database_async import db_all, async_session
from balancebot.collector.services.dataservice import DataService, Channel
from balancebot.common.models.observer import Observable, Observer
import ccxt.async_support as ccxt
from datetime import datetime, timedelta
from collections import deque
from balancebot.api.dbmodels.coin import Coin, Volume, OI
from balancebot.common.models.trade import Trade
from balancebot.common.models.volumeratio import VolumeRatio
from typing import Dict, List

from balancebot.common.models.singleton import Singleton
import aiohttp


class CoinTracker(Singleton, Observer):
    _ENDPOINT = 'https://ftx.com'

    VolumeObservable = Observable()
    OpenInterestObservable = Observable()

    def init(self,
             session: aiohttp.ClientSession = None,
             time_window: timedelta = timedelta(seconds=14400),
             max_time_range: timedelta = timedelta(days=13),
             time_frames: List[timedelta] = None,
             *args,
             **kwargs):

        self._session = session
        self._time_window = time_window
        self._max_time_range = max_time_range
        self._coins_by_name: Dict[str, Coin] = {}
        self._current_coin_volume: Dict[Coin, Volume] = {}
        self.data_service = DataService()

        self._ccxt = ccxt.ftx(
            config={
                'session': self._session
            }
        )

        self.volume_observable = Observable()
        self.oi_observable = Observable()

        self._on_volume_update = None
        self._on_open_interest_update = None

    async def _get(self, path: str, **kwargs):
        async with self._session.request('GET', self._ENDPOINT + path, **kwargs) as response:
            if response.status == 200:
                j = await response.json()
                if j.get('success'):
                    return j['result']
            else:
                print(await response.json())

    async def _get_markets_by_name(self, **kwargs):
        markets = await self._get('/api/markets', **kwargs)
        if markets:
            markets_by_name = {
                market["name"]: market for market in markets
            }
            return markets_by_name

    async def _get_market_data(self, market: str, start_time: datetime, **kwargs):
        return await self._get(
            f'/api/markets/{market}/candles',
            params={
                'start_time': str(start_time.timestamp()),
                'resolution': str(900)
            },
            **kwargs
        )

    async def run(self, http_session: aiohttp.ClientSession = None):

        if http_session:
            self._session = http_session

        if self._session is None:
            self._session = aiohttp.ClientSession()

        spot_markets_by_name = await self._get_markets_by_name(params={"type": "spot"})
        perp_markets_by_name = await self._get_markets_by_name(params={"type": "future"})

        if not spot_markets_by_name:
            raise Exception

        if not perp_markets_by_name:
            raise Exception

        coins = await db_all(select(Coin))
        self._coins_by_name = {coin.name: coin for coin in coins}

        for perp_name in perp_markets_by_name:
            if 'PERP' in perp_name:
                coin_name = self.get_coin_name(perp_name)
                spot_name = f'{coin_name}/USD'
                if spot_name in spot_markets_by_name and coin_name:
                    if coin_name not in self._coins_by_name:
                        coin = Coin(
                            name=coin_name,
                            exchange='ftx',
                        )
                        self._coins_by_name[coin_name] = coin
                        async_session.add(coin)
                    await self.data_service.subscribe(
                        'ftx',
                        Channel.TRADES,
                        observer=self,
                        symbol=perp_name
                    )
                    await self.data_service.subscribe(
                        'ftx',
                        Channel.TRADES,
                        observer=self,
                        symbol=spot_name
                    )

        await async_session.commit()

        print('Tracker Initialized')

        await asyncio.gather(
            asyncio.create_task(self._fetch_oi()),
            asyncio.create_task(self._update_forever())
        )

    def get_coin_name(self, symbol: str):
        split = symbol.split('-')
        if len(split) == 1:
            split = symbol.split('/')
        return split[0]

    async def update(self, *new_state):
        trade: Trade = new_state[0]

        coin = self._coins_by_name.get(
            self.get_coin_name(trade.symbol)
        )
        if coin:
            current_volume = self._current_coin_volume.get(coin)

            if not current_volume:
                current_volume = Volume(
                    coin_id=coin.id,
                    time=trade.time,
                    spot_buy=0.0,
                    spot_sell=0.0,
                    perp_buy=0.0,
                    perp_sell=0.0,
                )
                self._current_coin_volume[coin] = current_volume

            if trade.perp:
                if trade.side == 'buy':
                    current_volume.perp_buy += trade.size
                if trade.side == 'sell':
                    current_volume.perp_sell += trade.size
            else:
                if trade.side == 'buy':
                    current_volume.spot_buy += trade.size
                if trade.side == 'sell':
                    current_volume.spot_sell += trade.size

            if trade.time.minute != current_volume.time.minute:
                # TODO: avoid database spikes by smoothing / gathering volumes for commiting
                async_session.add(current_volume)
                await async_session.commit()
                self._current_coin_volume.pop(coin)

    async def _update_volume_history(self, coin: Coin):

        if coin.volume_history.spot_data:
            start_time = coin.volume_history.spot_data[len(coin.volume_history.spot_data) - 1]
        else:
            start_time = datetime(2022, 3, 22) - self._max_time_range

        spot_data = await self._get_market_data(coin.spot_ticker, start_time=start_time)
        perp_data = await self._get_market_data(coin.perp_ticker, start_time=start_time)

        if not coin.volume_history.perp_data:
            coin.volume_history.perp_data = deque(perp_data, maxlen=len(perp_data))
        else:
            coin.volume_history.perp_data.append(*perp_data)

        spot_aggr, perp_aggr = 0.0, 0.0
        coin.ratio_data = []
        coin.avg_ratio = 0.0

        for i in range(0, min(len(spot_data), len(perp_data))):
            spot_aggr += spot_data[i]["volume"]
            perp_aggr += perp_data[i]["volume"]
            ratio = VolumeRatio(
                date=datetime.fromisoformat(spot_data[i]["startTime"]),
                ratio=spot_aggr / perp_aggr if perp_aggr else 1
            )
            coin.avg_ratio += ratio.ratio
            coin.ratio_data.append(ratio)

        coin.avg_ratio /= len(coin.ratio_data) if coin.ratio_data else 1

        await self.volume_observable.notify(coin)

    async def _update_forever(self):
        while False:
            for coin in self._coins_by_name.values():
                await self._update_volume_history(coin)
            coins = list(self._coins_by_name.values())
            coins.sort(key=lambda x: x.avg_ratio, reverse=True)
            print('Biggest Accumulators')
            for i in range(0, 5):
                print(f'{coins[i].coin_name}: {coins[i].volume_history.avg_ratio}')
            await asyncio.sleep(self._time_window.total_seconds())

    async def _update_oi(self):

        all_futures = await self._get(
            '/api/futures'
        )

        now = datetime.now(tz=pytz.utc)

        if all_futures:
            for future in all_futures:
                symbol = future.get('name')
                if 'PERP' in symbol:
                    coin: Coin = self._coins_by_name.get(self.get_coin_name(symbol))
                    if coin:
                        coin.oi_history.append(
                            OI(
                                coin_id=coin.id,
                                time=now,
                                value=future.get('openInterestUsd')
                            )
                        )

        await async_session.commit()

        await self.oi_observable.notify(self._coins_by_name.values())

    async def _fetch_oi(self):
        while True:
            ts = time.time()
            await self._update_oi()
            #await asyncio.sleep(self._time_window.total_seconds() - time.time() - ts)
            await asyncio.sleep(self._time_window.total_seconds())

    def _on_message(self):
        pass


async def main():
    async with aiohttp.ClientSession() as session:
        fetcher = CoinTracker(session=session)
        await fetcher.run()


if __name__ == "__main__":
    asyncio.run(main())
