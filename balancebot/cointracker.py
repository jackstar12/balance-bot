import asyncio
import time
from balancebot.models.observer import Observable
import ccxt.async_support as ccxt
from datetime import datetime, timedelta
from collections import deque
from balancebot.models.coin import Coin, VolumeHistory, OI
from balancebot.models.volumeratio import VolumeRatio
from typing import Dict, List

from balancebot.models.singleton import Singleton
import aiohttp


class CoinTracker(Singleton):
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
        self._data: Dict[str, Coin] = {}
        self._ccxt = ccxt.ftx(
            config={
                'session': self._session
            }
        )

        self.volume_observable = Observable()
        self.oi_observable = Observable()

        self._on_volume_update = None
        self._on_open_interest_update = None

    def start(self):
        asyncio.create_task(self.run())

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

    async def run(self, http_session: aiohttp.ClientSession):

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

        for perp_name in perp_markets_by_name:
            if 'PERP' in perp_name:
                coin_name = perp_name.split('-')[0]
                spot_name = f'{coin_name}/USD'
                if spot_name in spot_markets_by_name:
                    self._data[coin_name] = Coin(
                        coin_name=coin_name,
                        spot_ticker=spot_name,
                        perp_ticker=perp_name,
                        volume_history=VolumeHistory(
                            spot_data=None,
                            perp_data=None,
                            ratio_data=None,
                            avg_ratio=None
                        ),
                        open_interest_data=None
                    )

        print('Tracker Initialized')

        await asyncio.gather(
            asyncio.create_task(self._fetch_oi()),
            asyncio.create_task(self._update_forever())
        )

    async def _update_volume_history(self, coin: Coin):

        if coin.volume_history.spot_data:
            start_time = coin.volume_history.spot_data[len(coin.volume_history.spot_data) - 1]
        else:
            start_time = datetime(2022, 3, 22) - self._max_time_range

        spot_data = await self._get_market_data(coin.spot_ticker, start_time=start_time)
        perp_data = await self._get_market_data(coin.perp_ticker, start_time=start_time)

        if not coin.perp_data:
            coin.perp_data = deque(perp_data, maxlen=len(perp_data))
        else:
            coin.perp_data.append(*perp_data)

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

        self.volume_observable.notify(coin)

    async def _update_forever(self):
        while True:
            for coin in self._data.values():
                await self._update_volume_history(coin)
            coins = list(self._data.values())
            coins.sort(key=lambda x: x.avg_ratio, reverse=True)
            print('Biggest Accumulators')
            for i in range(0, 5):
                print(f'{coins[i].coin_name}: {coins[i].volume_history.avg_ratio}')
            await asyncio.sleep(self._time_window.total_seconds())

    async def _update_oi(self):

        all_futures = await self._get(
            '/api/futures'
        )

        if all_futures:
            for future in all_futures:
                name = future.get('name')
                if 'PERP' in name:
                    coin_name = name.split('-')[0]
                    coin = self._data.get(coin_name)
                    if coin and coin.open_interest_data:
                        coin.open_interest_data.append(
                            OI(time=datetime.now(), value=future.get('openInterestUsd'))
                        )

        self.oi_observable.notify(self._data.values())

    async def _fetch_oi(self):
        while True:
            ts = time.time()
            await self._update_oi()
            await asyncio.sleep(self._time_window.total_seconds() - time.time() - ts)

    def _on_message(self):
        pass


async def main():
    async with aiohttp.ClientSession() as session:
        fetcher = CoinTracker(session=session)
        await fetcher.start()


if __name__ == "__main__":
    asyncio.run(main())
