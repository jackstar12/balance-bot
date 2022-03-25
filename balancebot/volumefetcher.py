import asyncio
from datetime import datetime
from collections import deque
from models.volumeratiohistory import VolumeRatioHistory
from models.volumeratio import VolumeRatio
from typing import Dict
from .Exchanges.ftx.websocket import FtxWebsocketClient
from .models.singleton import Singleton
import aiohttp


class VolumeFetcher(Singleton):
    _ENDPOINT = 'https://ftx.com/api/'

    def init(self, session: aiohttp.ClientSession, *args, **kwargs):
        self._session = session
        self._ws = FtxWebsocketClient(session, on_message_callback=self._on_message)
        self._data: Dict[str, VolumeRatioHistory] = {}

    def start(self):
        self._ws.connect()
        self._ws.get_ticker('')

    async def _get(self, path: str, **kwargs):
        async with self._session.request('GET', self._ENDPOINT + path, **kwargs) as response:
            if response.status == 200:
                j = await response.json()
                if j.get('success'):
                    return j['result']

    async def _get_markets_by_name(self, **kwargs):
        markets = await self._get('markets', **kwargs)
        if markets:
            markets_by_name = {
                market["name"]: market for market in markets
            }
            return markets_by_name

    async def _get_market_data(self, market: str, **kwargs):
        return await self._get(
            f'markets/{market}/candles',
            params={
                'start_time': str(datetime.now()),
                'resolution': str(10 * 60)
            }
        )

    async def _bootstrap(self):

        spot_markets_by_name = await self._get_markets_by_name(params={"type": "spot"})
        perp_markets_by_name = await self._get_markets_by_name(params={"type": "future"})

        if not spot_markets_by_name:
            raise Exception

        if not perp_markets_by_name:
            raise Exception

        for perp_name in perp_markets_by_name:
            coin_name = perp_name.split('-')[0]
            spot_name = spot_markets_by_name.get(f'{coin_name}/USD')
            if spot_name:
                spot_data = await self._get_market_data(spot_name)
                perp_data = await self._get_market_data(perp_name)

                spot_aggr, perp_aggr = 0.0, 0.0
                ratio = []
                now = datetime.now()
                for i in range(0, min(len(spot_data), len(perp_data))):
                    spot_aggr += spot_data[i]["volume"]
                    perp_aggr += perp_data[i]["volume"]
                    ratio.append(
                        VolumeRatio(date=now, ratio=spot_aggr / perp_aggr)
                    )

                self._data[coin_name] = VolumeRatioHistory(
                    spot_name=spot_name,
                    spot_data=deque(spot_data, maxlen=len(spot_data)),
                    perp_name=perp_name,
                    perp_data=deque(perp_data, maxlen=len(perp_data))
                )

        asyncio.create_task(self._update_forever())

    async def _update_forever(self):
        while True:
            await asyncio.sleep(10 * 60)
            raise NotImplementedError()


    def _on_message(self):
        pass

    pass
