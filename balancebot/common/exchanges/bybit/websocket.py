import hmac
import time
import urllib.parse

import aiohttp
from typing_extensions import Self

from balancebot.common import customjson, utils
from balancebot.common.models.async_websocket_manager import WebsocketManager
from typing import TYPE_CHECKING, Callable, List, Dict, Awaitable


class BybitWebsocketClient(WebsocketManager):

    def __init__(self,
                 session: aiohttp.ClientSession,
                 get_url: Callable[..., str],
                 on_message: Callable[[Self, Dict], Awaitable],
                 **kwargs):
        super().__init__(session=session, get_url=get_url, on_message=self._on_message, ping_forever_seconds=30, **kwargs)
        self._on_data_message = on_message

    async def _send_op(self, op: str, *args):
        return await self.send_json({'op': op, 'args': args})

    # https://bybit-exchange.github.io/docs/inverse/#t-heartbeat
    async def ping(self):
        await self._send_op("ping")

    # https://bybit-exchange.github.io/docs/inverse/#t-subscribe
    async def subscribe(self, topic: str, *filters: str):
        filters = '|'.join(filters)
        if filters:
            filters = '.' + filters
        return await self._send_op("subscribe", f"{topic}{filters}")

    # https://bybit-exchange.github.io/docs/inverse/#t-unsubscribe
    async def unsubscribe(self, topic: str, *filters: str):
        filters = '|'.join(filters)
        if filters:
            filters = '.' + filters
        await self._send_op("unsubscribe", f"{topic}{filters}")

    async def authenticate(self, api_key: str, api_secret: str):
        expires = int((time.time() + 10) * 1000)
        scheme, netloc, path, query, fragment = urllib.parse.urlsplit(self._get_url())
        _val = f'GET{path}{expires}'
        sign = str(hmac.new(
            api_secret.encode('utf-8'),
            _val.encode('utf-8'),
            digestmod='sha256'
        ).hexdigest())
        await self._send_op("auth", api_key, expires, sign)

    async def _on_message(self, ws: WebsocketManager, raw_message: str):
        message = customjson.loads(raw_message)

        request = message.get("request")
        if request:
            op = request["op"]

            if op == "subscribe":
                return
            if op == "ping":
                return
            if op == "auth":
                return
        else:
            await utils.call_unknown_function(
                self._on_data_message, self, message
            )


