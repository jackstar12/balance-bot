from __future__ import annotations

import logging
from typing import Callable, TYPE_CHECKING

import aiohttp

import core
from database.models.async_websocket_manager import WebsocketManager

if TYPE_CHECKING:
    from common.exchanges.binance.worker import BinanceFutures


# https://binance-docs.github.io/apidocs/futures/en/#user-data-streams
class FuturesWebsocketClient(WebsocketManager):
    _ENDPOINT = 'wss://fstream.binance.com'
    _SANDBOX_ENDPOINT = 'wss://stream.binancefuture.com'

    def __init__(self, binance: BinanceFutures, session: aiohttp.ClientSession, on_message: Callable = None):
        super().__init__(session=session, get_url=self._get_url, ping_forever_seconds=50*60)
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
            await core.call_unknown_function(self._on_message, message)

    async def start(self):
        await self._renew_listen_key()

    async def stop(self):
        self._listenKey = None
        await self.close()

    async def _start_user_stream(self):
        response = await self._binance.post('/fapi/v1/listenKey')
        if response.get('msg') is None:
            return response['listenKey']
        else:
            return None

    async def _renew_listen_key(self):
        self._listenKey = await self._start_user_stream()
        await self.reconnect()

    async def ping(self):
        logging.info('Keep alive binance websocket')
        await self._binance.put('/fapi/v1/listenKey')
