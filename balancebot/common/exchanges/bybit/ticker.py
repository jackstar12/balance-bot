from decimal import Decimal
from typing import Dict

import aiohttp

from balancebot.common.exchanges.exchangeticker import ExchangeTicker, Channel
from balancebot.common.config import TESTING
from balancebot.common.exchanges.bybit.websocket import BybitWebsocketClient
from balancebot.common.models.async_websocket_manager import WebsocketManager
from balancebot.common.models.ticker import Ticker


class _BybitTicker(ExchangeTicker):
    _WS_ENDPOINT = None
    EXCHANGE = ''

    def __init__(self, session: aiohttp.ClientSession):
        super().__init__(session)
        self._ws = BybitWebsocketClient(session,
                                        self._get_url,
                                        self._on_message)

    def _get_url(self):
        return self._WS_ENDPOINT

    async def _subscribe(self, channel: Channel, **kwargs):
        # I have no idea why the values have to be compared
        if channel.value == Channel.TICKER.value:
            res = await self._ws.subscribe("trade", kwargs["symbol"])
            pass

    async def _unsubscribe(self, channel: Channel, **kwargs):
        if channel.value == Channel.TICKER.value:
            res = await self._ws.unsubscribe("trade", kwargs["symbol"])
            pass

    async def connect(self):
        await self._ws.connect()

    async def _on_message(self, ws: WebsocketManager, message: Dict):
        all_data = message["data"]
        if "trade" in message["topic"]:
            data = all_data[0]
            await self._callbacks.get(Channel.TICKER.value).notify(
                Ticker(
                    symbol=data["symbol"],
                    exchange=self.EXCHANGE,
                    price=Decimal(data["price"]),
                    ts=data["trade_time_ms"] / 1000
                )
            )


class BybitLinearTicker(_BybitTicker):
    _WS_ENDPOINT = 'wss://stream-testnet.bybit.com/realtime_public' if TESTING else 'wss://stream.bybit.com/realtime_public'
    EXCHANGE = 'bybit-linear'


class BybitInverseTicker(_BybitTicker):
    _WS_ENDPOINT = 'wss://stream-testnet.bybit.com/realtime' if TESTING else 'wss://stream.bybit.com/realtime'
    EXCHANGE = 'bybit-inverse'

