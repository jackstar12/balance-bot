import json

from datetime import timedelta
from threading import Timer, Lock
from typing import Callable

from Exchanges.binance.websocket_manager import WebsocketManager
from models.trade import Trade
from datetime import datetime


# https://binance-docs.github.io/apidocs/futures/en/#user-data-streams
class FuturesWebsocketClient(WebsocketManager):

    _ENDPOINT = 'wss://fstream.binance.com'

    def __init__(self, client, on_message: Callable = None):
        super().__init__()
        self._client = client
        self._listenKey = None
        self._key_lock = Lock()
        self._keep_alive_timer = None
        self._on_message = on_message

    def _get_url(self):
        return self._ENDPOINT + f'/ws/{self._listenKey}'

    def _on_message(self, ws, message):
        message = json.loads(message)
        event = message['e']
        data = message['o']
        if event == 'listenKeyExpired':
            self._renew_listen_key()
        elif callable(self._on_message):
            self._on_message(self, message)

    def start(self):
        if self._listenKey is None:
            self._listenKey = self._client.start_user_stream()
            self._keep_alive()
            self.connect()

    def stop(self):
        with self._key_lock:
            self._listenKey = None

    def _renew_listen_key(self):
        with self._key_lock:
            self._listenKey = self._client.start_user_stream()
        self.reconnect()

    def _keep_alive(self):
        with self._key_lock:
            if self._listenKey:
                self._client.keep_alive(self._listenKey)
                keep_alive = Timer(timedelta(minutes=60).total_seconds(), self._keep_alive)
                keep_alive.daemon = True
                keep_alive.start()

