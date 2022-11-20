from decimal import Decimal
from typing import Dict

import aiohttp

from common.exchanges.exchangeticker import ExchangeTicker, Channel
from core.env import TESTING
from common.exchanges.bybit.websocket import BybitWebsocketClient
from database.models.async_websocket_manager import WebsocketManager
from database.models.ticker import Ticker


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
        if channel == Channel.TICKER:
            res = await self._ws.subscribe("trade", kwargs["symbol"])
            pass

    async def _unsubscribe(self, channel: Channel, **kwargs):
        if channel == Channel.TICKER:
            res = await self._ws.unsubscribe("trade", kwargs["symbol"])
            pass

    async def connect(self):
        await self._ws.connect()

    async def disconnect(self):
        await self._ws.close()

    async def _on_message(self, ws: WebsocketManager, message: Dict):
        all_data = message["data"]
        if "trade" in message["topic"]:
            data = all_data[0]
            await self._callbacks.get(Channel.TICKER).notify(
                Ticker(
                    symbol=data["symbol"],
                    exchange=self.EXCHANGE,
                    price=Decimal(data["price"]),
                )
            )


class BybitLinearTicker(_BybitTicker):
    _WS_ENDPOINT = 'wss://stream-testnet.bybit.com/realtime_public' if TESTING else 'wss://stream.bybit.com/realtime_public'
    EXCHANGE = 'bybit-linear'


class BybitInverseTicker(_BybitTicker):
    _WS_ENDPOINT = 'wss://stream-testnet.bybit.com/realtime' if TESTING else 'wss://stream.bybit.com/realtime'
    EXCHANGE = 'bybit-inverse'

