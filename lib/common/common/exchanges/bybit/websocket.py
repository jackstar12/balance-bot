import hmac
import logging
import time
import urllib.parse

import aiohttp
from typing_extensions import Self

import core
from database.models.async_websocket_manager import WebsocketManager
from typing import Callable, Dict, Awaitable, Any


class BybitWebsocketClient(WebsocketManager):

    def __init__(self,
                 session: aiohttp.ClientSession,
                 get_url: Callable[..., str] | str,
                 on_message: Callable[[Self, Dict], Awaitable],
                 sandbox: bool = False,
                 **kwargs):
        super().__init__(session=session, get_url=get_url, ping_forever_seconds=30, **kwargs)
        self._on_data_message = on_message

    def _get_request_id(self, request: dict):
        if request['op'] == 'auth':
            return 'auth'
        return request['op'] + ''.join(str(arg) for arg in request['args'])

    def _get_message_id(self, message: dict) -> Any:
        return message.get('req_id')
        if message.get('op') == 'auth':
            return 'auth'
        elif 'request' in message:
            return self._get_request_id(message['request'])

    async def _send_op(self, op: str, *args):
        request = {'op': op, 'args': args, 'req_id': self._generate_id()}
        #return await self.send_json(request, msg_id=self._get_request_id(request))
        return await self.send_json(request, msg_id=request['req_id'])

    # https://bybit-exchange.github.io/docs/futuresV2/inverse/#t-heartbeat
    async def ping(self):
        await self._send_op("ping")

    # https://bybit-exchange.github.io/docs/futuresV2/inverse/#t-subscribe
    async def subscribe(self, topic: str, *filters: str):
        filters = '|'.join(filters)
        if filters:
            filters = '.' + filters
        return await self._send_op("subscribe", f"{topic}{filters}")

    # https://bybit-exchange.github.io/docs/futuresV2/inverse/#t-unsubscribe
    async def unsubscribe(self, topic: str, *filters: str):
        filters = '|'.join(filters)
        if filters:
            filters = '.' + filters
        await self._send_op("unsubscribe", f"{topic}{filters}")

    async def authenticate(self, api_key: str, api_secret: str):
        expires = int((time.time() + 10) * 1000)
        _val = f'GET/realtime{expires}'
        sign = str(hmac.new(
            api_secret.encode('utf-8'),
            _val.encode('utf-8'),
            digestmod='sha256'
        ).hexdigest())
        return await self._send_op("auth", api_key, expires, sign)

    async def _on_message(self, ws: WebsocketManager, message: dict):
        op = message.get("op")
        if op:
            if op == "subscribe":
                return
            if op == "ping":
                return
            if op == "auth":
                return
        else:
            await core.return_unknown_function(
                self._on_data_message, self, message
            )

