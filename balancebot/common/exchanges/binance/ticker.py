import json
from decimal import Decimal
from typing import List

from balancebot.api.settings import settings
from balancebot.collector.exchangeticker import ExchangeTicker, Channel
from balancebot.common.config import TESTING
from balancebot.common.models.async_websocket_manager import WebsocketManager
from balancebot.common.models.ticker import Ticker


def _symbol_stream(symbol: str):
    return f'{symbol.lower()}@aggTrade'


class BinanceFuturesTicker(WebsocketManager, ExchangeTicker):
    _ENDPOINT = 'wss://stream.binancefuture.com' if TESTING else 'wss://fstream.binance.com'
    #_ENDPOINT = 'wss://fstream.binance.com'

    def __init__(self, *args, **kwargs):
        WebsocketManager.__init__(self, *args, **kwargs)
        ExchangeTicker.__init__(self, *args, **kwargs)

    def _get_url(self):
        return self._ENDPOINT + f'/ws'

    async def _subscribe(self, channel: Channel, **kwargs):
        if channel.value == Channel.TICKER.value:
            await self.send_message("SUBSCRIBE", [_symbol_stream(kwargs.get("symbol"))])
        elif channel.value is Channel.TRADES.value:
            await self._ws.get_fills()

    async def _unsubscribe(self, channel: Channel, **kwargs):
        if channel.value == Channel.TICKER.value:
            await self.send_message("UNSUBSCRIBE", [_symbol_stream(kwargs.get("symbol"))])

    async def send_message(self, method: str, params: List[str], id: int = 1):
        await self.send_json({
            "method": method,
            "params": params,
            "id": id
        })

    async def _on_message(self, ws, msg_raw):
        msg = json.loads(msg_raw)
        event = msg.get('e')
        if event == "aggTrade":
            await self._callbacks.get(Channel.TICKER.value).notify(
                Ticker(
                    symbol=msg['s'],
                    price=Decimal(msg['p']),
                    ts=msg['T'],
                    exchange='binance-futures'
                )
            )
