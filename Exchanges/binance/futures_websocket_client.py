import asyncio
import json
import logging
import asyncio

from datetime import timedelta
from threading import Timer, Lock
from typing import Callable

from Exchanges.binance.websocket_manager import WebsocketManager
from datetime import datetime
import aiohttp

# https://binance-docs.github.io/apidocs/futures/en/#user-data-streams
class FuturesWebsocketClient(WebsocketManager):

    _ENDPOINT = 'wss://fstream.binance.com'

    def __init__(self, client, session: aiohttp.ClientSession, on_message: Callable = None):
        super().__init__(session=session)
        self._client = client
        self._listenKey = None
        self._key_lock = Lock()
        self._keep_alive_timer = None
        self._on_message = on_message

    def _get_url(self):
        return self._ENDPOINT + f'/ws/{self._listenKey}'

    def _on_message(self, ws, message):
        event = message['e']
        print(message)
        if event == 'listenKeyExpired':
            self._renew_listen_key()
        elif callable(self._on_message):
            self._on_message(self, message)

    async def start(self):
        if self._listenKey is None:
            self._listenKey = await self._client.start_user_stream()
            await self.connect()

    def stop(self):
        with self._key_lock:
            self._listenKey = None

    def _renew_listen_key(self):
        with self._key_lock:
            self._listenKey = asyncio.run(self._client.start_user_stream())
        self.reconnect()

    def _keep_alive(self):
        with self._key_lock:
            if self._listenKey:
                logging.info('Trying to reconnect binance websocket')
                self._listenKey = self._client.start_user_stream()
                keep_alive = Timer(timedelta(minutes=45).total_seconds(), self._keep_alive)
                keep_alive.daemon = True
                keep_alive.start()
