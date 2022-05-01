import logging
import asyncio
from typing import Callable

from balancebot.common import utils
from balancebot.api.settings import settings
from balancebot.common.models.async_websocket_manager import WebsocketManager
import aiohttp


# https://binance-docs.github.io/apidocs/futures/en/#user-data-streams
class FuturesWebsocketClient(WebsocketManager):
    _ENDPOINT = 'wss://stream.binancefuture.com' if settings.testing else 'wss://fstream.binance.com'

    def __init__(self, client, session: aiohttp.ClientSession, on_message: Callable = None):
        super().__init__(session=session)
        self._client = client
        self._listenKey = None
        self._on_message = on_message

    def _get_url(self):
        return self._ENDPOINT + f'/ws/{self._listenKey}'

    async def _on_message(self, ws, message):
        event = message['e']
        print('BINANCE EVENT: ', event)
        if event == 'listenKeyExpired':
            await self._renew_listen_key()
        elif callable(self._on_message):
            await utils.call_unknown_function(self._on_message, message)

    async def start(self):
        await self._renew_listen_key()
        asyncio.create_task(self._keep_alive())

    def stop(self):
        self._listenKey = None

    async def _renew_listen_key(self):
        self._listenKey = await self._client.start_user_stream()
        await self.reconnect()

    async def _keep_alive(self):
        while self._ws and not self._ws.closed:
            # Ping binance every 50 minutes
            if self._listenKey:
                logging.info('Keep alive binance websocket')
                await self._client.keep_alive()
                await asyncio.sleep(50 * 60)
            else:
                await self.reconnect()
                break
