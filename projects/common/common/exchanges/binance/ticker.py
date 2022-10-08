from decimal import Decimal

from common.exchanges.exchangeworker import ExchangeWorker
from common.models.trade import Trade
from common.exchanges.exchangeticker import ExchangeTicker, Channel
from common.models.async_websocket_manager import WebsocketManager
from common.models.ticker import Ticker


# https://binance-docs.github.io/apidocs/futures/en/#aggregate-trade-streams
def _trade_stream(symbol: str):
    return f'{symbol.lower()}@aggTrade'


# https://binance-docs.github.io/apidocs/futures/en/#individual-symbol-ticker-streams
def _ticker_stream(symbol: str):
    return f'{symbol.lower()}@ticker'


# https://binance-docs.github.io/apidocs/futures/en/#websocket-market-streams
class BinanceFuturesTicker(WebsocketManager, ExchangeTicker):
    # _ENDPOINT = 'wss://stream.binancefuture.com' if TESTING else 'wss://fstream.binance.com'
    _ENDPOINT = 'wss://fstream.binance.com'

    def __init__(self, *args, **kwargs):
        WebsocketManager.__init__(self, *args, **kwargs, get_url=self._get_url)
        ExchangeTicker.__init__(self, *args, **kwargs)

    def _get_url(self):
        return self._ENDPOINT + f'/ws/'

    # def _get_message_id(self, message: dict) -> Any:
    #     return message['id']

    async def disconnect(self):
        await self.close()

    async def _subscribe(self, channel: Channel, **kwargs):
        if channel.value == Channel.TICKER.value:
            await self.send_message("SUBSCRIBE", _ticker_stream(kwargs.get("symbol")))
        elif channel.value is Channel.TRADES.value:
            await self.send_message("SUBSCRIBE", _trade_stream(kwargs.get("symbol")))

    async def _unsubscribe(self, channel: Channel, **kwargs):
        if channel.value == Channel.TICKER.value:
            await self.send_message("UNSUBSCRIBE", _ticker_stream(kwargs.get("symbol")))
        if channel.value == Channel.TRADES.value:
            await self.send_message("UNSUBSCRIBE", _trade_stream(kwargs.get("symbol")))

    async def send_message(self, method: str, *params: str):
        id = self._generate_id()
        await self.send_json(
            {
                "method": method,
                "params": params,
                "id": id
            },
            msg_id=id
        )

    async def _on_message(self, ws, msg):
        event = msg.get('e')
        if event == "aggTrade":
            await self._callbacks.get(Channel.TRADES.value).notify(
                Trade(
                    symbol=msg['s'],
                    side='BUY' if msg['m'] else 'SELL',
                    size=msg['q'],
                    price=Decimal(msg['p']),
                    exchange='binance-futures',
                    time=ExchangeWorker.parse_ms(float(msg['E'])),
                    perp=True
                )
            )
        if event == "24hrTicker":
            await self._callbacks.get(Channel.TICKER.value).notify(
                Ticker(
                    symbol=msg['s'],
                    price=Decimal(msg['c']),
                    exchange='binance-futures'
                )
            )
