from __future__ import annotations
import logging
import asyncio
from abc import ABC
from typing import Callable, TYPE_CHECKING

from tradealpha.common import utils
from tradealpha.common.config import TESTING
from tradealpha.common.models.async_websocket_manager import WebsocketManager
import aiohttp


if TYPE_CHECKING:
    from tradealpha.common.exchanges.binance.worker import BinanceFutures

# https://binance-docs.github.io/apidocs/futures/en/#user-data-streams
class FuturesWebsocketClient(WebsocketManager):
    _ENDPOINT = 'wss://fstream.binance.com'
    _SANDBOX_ENDPOINT = 'wss://stream.binancefuture.com'

    def __init__(self, binance: BinanceFutures, session: aiohttp.ClientSession, on_message: Callable = None):
        super().__init__(session=session, get_url=self._get_url)
        self._binance = binance
        self._listenKey = None
        self._on_message = on_message

    def _get_url(self):
        return (self._SANDBOX_ENDPOINT if self._binance.client.sandbox else self._ENDPOINT) + f'/ws/{self._listenKey}'

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

    async def stop(self):
        self._listenKey = None
        await self.close()

    async def _start_user_stream(self):
        response = await self._binance._post('/fapi/v1/listenKey')
        if response.get('msg') is None:
            return response['listenKey']
        else:
            return None

    async def _renew_listen_key(self):
        self._listenKey = await self._start_user_stream()
        await self.reconnect()

    async def _keep_alive(self):
        while self._ws and not self._ws.closed:
            # Ping binance every 50 minutes
            if self._listenKey:
                logging.info('Keep alive binance websocket')
                await self._binance._put('/fapi/v1/listenKey')
                await asyncio.sleep(50 * 60)
            else:
                await self.reconnect()
