import asyncio
from datetime import datetime, timedelta
from collections import deque
from models.volumeratiohistory import VolumeRatioHistory
from models.volumeratio import VolumeRatio
from typing import Dict, List

from models.singleton import Singleton
import aiohttp


class VolumeFetcher(Singleton):
    _ENDPOINT = 'https://ftx.com/api/'

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
        self._data: Dict[str, VolumeRatioHistory] = {}

    async def start(self):
        await self._bootstrap()

    async def _get(self, path: str, **kwargs):
        async with self._session.request('GET', self._ENDPOINT + path, **kwargs) as response:
            if response.status == 200:
                j = await response.json()
                if j.get('success'):
                    return j['result']
            else:
                print(await response.json())

    async def _get_markets_by_name(self, **kwargs):
        markets = await self._get('markets', **kwargs)
        if markets:
            markets_by_name = {
                market["name"]: market for market in markets
            }
            return markets_by_name

    async def _get_market_data(self, market: str, start_time: datetime, **kwargs):
        return await self._get(
            f'markets/{market}/candles',
            params={
                'start_time': str(start_time.timestamp()),
                'resolution': str(900)
            },
            **kwargs
        )

    async def _bootstrap(self):

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
                    self._data[coin_name] = VolumeRatioHistory(
                        coin_name=coin_name,
                        spot_name=spot_name,
                        perp_name=perp_name,
                        spot_data=None,
                        perp_data=None,
                        ratio_data=None,
                        avg_ratio=None
                    )

        await self._update_forever()

    async def _update_volume_history(self, coin: VolumeRatioHistory):

        if coin.spot_data:
            start_time = coin.spot_data[len(coin.spot_data) - 1]
        else:
            start_time = datetime(2022, 3, 22) - self._max_time_range

        spot_data = await self._get_market_data(coin.spot_name, start_time=start_time)
        perp_data = await self._get_market_data(coin.perp_name, start_time=start_time)

        if not coin.perp_data:
            coin.perp_data = deque(perp_data, maxlen=len(perp_data))
        else:
            coin.perp_data.append(*perp_data)

        if not coin.perp_data:
            coin.perp_data

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

    async def _update_forever(self):
        while True:
            for coin in self._data.values():
                await self._update_volume_history(coin)
            coins = list(self._data.values())
            coins.sort(key=lambda x: x.avg_ratio, reverse=True)
            print('Biggest Accumulators')
            for i in range(0, 5):
                print(f'{coins[i].coin_name}: {coins[i].avg_ratio}')
            await asyncio.sleep(self._time_window.total_seconds())

    def _on_message(self):
        pass

    pass


async def main():
    fetcher = VolumeFetcher()
    await fetcher.start()


if __name__ == "__main__":
    asyncio.run(main())
