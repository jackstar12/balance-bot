from datetime import datetime

from .Exchanges.ftx.websocket import FtxWebsocketClient
from .models.singleton import Singleton
import aiohttp


class VolumeFetcher(Singleton):
    _ENDPOINT = 'https://ftx.com/api/'

    def init(self, session: aiohttp.ClientSession, *args, **kwargs):

        self._session = session
        self._ws = FtxWebsocketClient(session, on_message_callback=self._on_message)

    def start(self):
        self._ws.connect()
        self._ws.get_ticker('')

    def _get(self, path: str, **kwargs):
        return self._session.request('GET', self._ENDPOINT + path, **kwargs)

    async def _bootstrap(self):

        markets = None
        async with self._get('markets') as response:
            if response.status == 200:
                markets = await response.json()

        if markets:
            for market in markets:
                async with self._get(
                        f'markets/{market["name"]}',
                        params={
                            'start_time': str(datetime.now()),
                            'resolution': str(10 * 60)
                        }
                ) as response:
                    if response.status == 200:
                        print(response.json())

    def _on_message(self):
        pass

    pass