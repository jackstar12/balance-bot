import hmac
import json
import time
import zlib
import sys
from collections import defaultdict, deque
from itertools import zip_longest
from typing import DefaultDict, Deque, List, Dict, Tuple, Optional
from gevent.event import Event

from Exchanges.ftx.websocket_manager import WebsocketManager


class FtxWebsocketClient(WebsocketManager):
    _ENDPOINT = 'wss://ftx.com/ws/'

    def _get_url(self) -> str:
        return self._ENDPOINT

    def __init__(self, api_key=None, api_secret=None, on_message_callback=None, subaccount=None) -> None:
        super().__init__()
        self._fills: Deque = deque([], maxlen=10000)
        self._api_key = api_key
        self._api_secret = api_secret
        self._orderbook_update_events: DefaultDict[str, Event] = defaultdict(Event)
        self._reset_data()
        self._on_message_callback = on_message_callback
        self._subaccount = subaccount

    def _on_open(self, ws):
        self._reset_data()

    def _reset_data(self) -> None:
        self._subscriptions: List[Dict] = []
        self._logged_in = False
        self._orders: DefaultDict[int, Dict] = defaultdict(dict)
        self._tickers: DefaultDict[str, Dict] = defaultdict(dict)
        self._last_received_orderbook_data_at: float = 0.0

    def _login(self) -> None:
        ts = int(time.time() * 1000)
        self.send_json({'op': 'login', 'args': {
            'key': self._api_key,
            'sign': hmac.new(
                self._api_secret.encode(), f'{ts}websocket_login'.encode(), 'sha256').hexdigest(),
            'time': ts,
            'subaccount': self._subaccount
        }})
        self._logged_in = True

    def _subscribe(self, subscription: Dict) -> None:
        self.send_json({'op': 'subscribe', **subscription})
        self._subscriptions.append(subscription)

    def _unsubscribe(self, subscription: Dict) -> None:
        self.send_json({'op': 'unsubscribe', **subscription})
        while subscription in self._subscriptions:
            self._subscriptions.remove(subscription)

    def get_fills(self) -> List[Dict]:
        if not self._logged_in:
            self._login()
        subscription = {'channel': 'fills'}
        if subscription not in self._subscriptions:
            self._subscribe(subscription)
        return list(self._fills.copy())

    def get_orders(self) -> Dict[int, Dict]:
        if not self._logged_in:
            self._login()
        subscription = {'channel': 'orders'}
        if subscription not in self._subscriptions:
            self._subscribe(subscription)
        return dict(self._orders.copy())

    def get_ticker(self, market: str) -> Dict:
        subscription = {'channel': 'ticker', 'market': market}
        if subscription not in self._subscriptions:
            self._subscribe(subscription)
        return self._tickers[market]

    def ping(self):
        self.send_json({
            'op': 'ping'
        })

    def _handle_ticker_message(self, message: Dict) -> None:
        self._tickers[message['market']] = message['data']

    def _handle_fills_message(self, message: Dict) -> None:
        self._fills.append(message['data'])

    def _handle_orders_message(self, message: Dict) -> None:
        data = message['data']
        self._orders.update({data['id']: data})

    def _on_message(self, ws, raw_message: str) -> None:
        message = json.loads(raw_message)
        message_type = message['type']
        if message_type in {'subscribed', 'unsubscribed', 'pong'}:
            return
        elif message_type == 'info':
            if message['code'] == 20001:
                return self.reconnect()
        elif message_type == 'error':
            raise Exception(message)
        channel = message['channel']

        if channel == 'ticker':
            self._handle_ticker_message(message)
        elif channel == 'fills':
            self._handle_fills_message(message)
        elif channel == 'orders':
            self._handle_orders_message(message)
        if self._on_message_callback:
            if callable(self._on_message_callback):
                self._on_message_callback(self, message)
