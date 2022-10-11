import hmac
import time
from collections import defaultdict, deque
from typing import DefaultDict, Deque, List, Dict

import aiohttp

import core
from database.models.async_websocket_manager import WebsocketManager


class FtxWebsocketClient(WebsocketManager):
    _ENDPOINT = 'wss://ftx.com/ws/'

    def _get_url(self) -> str:
        return self._ENDPOINT

    def __init__(self, session: aiohttp.ClientSession, api_key=None, api_secret=None, on_message_callback=None, subaccount=None) -> None:
        super().__init__(session=session, get_url=lambda: self._ENDPOINT, ping_forever_seconds=15)
        self._fills: Deque = deque([], maxlen=10000)
        self._api_key = api_key
        self._api_secret = api_secret
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

    async def _login(self) -> None:
        ts = int(time.time() * 1000)
        await self.send_json({'op': 'login', 'args': {
            'key': self._api_key,
            'sign': hmac.new(
                self._api_secret.encode(), f'{ts}websocket_login'.encode(), 'sha256').hexdigest(),
            'time': ts,
            'subaccount': self._subaccount
        }})
        self._logged_in = True

    async def _subscribe(self, subscription: Dict) -> None:
        await self.send_json({'op': 'subscribe', **subscription})
        self._subscriptions.append(subscription)

    async def _unsubscribe(self, subscription: Dict) -> None:
        await self.send_json({'op': 'unsubscribe', **subscription})
        while subscription in self._subscriptions:
            self._subscriptions.remove(subscription)

    async def get_fills(self) -> List[Dict]:
        if not self._logged_in:
            await self._login()
        subscription = {'channel': 'fills'}
        if subscription not in self._subscriptions:
            await self._subscribe(subscription)
        return list(self._fills.copy())

    async def get_orders(self) -> Dict[int, Dict]:
        if not self._logged_in:
            await self._login()
        subscription = {'channel': 'orders'}
        if subscription not in self._subscriptions:
            await self._subscribe(subscription)
        return dict(self._orders.copy())

    async def get_ticker(self, market: str) -> Dict:
        subscription = {'channel': 'ticker', 'market': market}
        if subscription not in self._subscriptions:
            await self._subscribe(subscription)
        return self._tickers[market]

    async def get_trades(self, market: str) -> Dict:
        subscription = {'channel': 'trades', 'market': market}
        if subscription not in self._subscriptions:
            await self._subscribe(subscription)
        return self._tickers[market]

    async def ping(self):
        await self.send_json({
            'op': 'ping'
        })

    def _handle_ticker_message(self, message: Dict) -> None:
        self._tickers[message['market']] = message['data']

    def _handle_fills_message(self, message: Dict) -> None:
        self._fills.append(message['data'])

    def _handle_orders_message(self, message: Dict) -> None:
        data = message['data']
        self._orders.update({data['id']: data})

    async def _on_message(self, ws, message: dict) -> None:
        message_type = message['type']
        if message_type in {'subscribed', 'unsubscribed', 'pong'}:
            return
        elif message_type == 'info':
            if message['code'] == 20001:
                return await self.reconnect()
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
                await core.call_unknown_function(self._on_message_callback, message)
