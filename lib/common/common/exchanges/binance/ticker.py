from decimal import Decimal

from common.exchanges.exchangeticker import ExchangeTicker, Channel, Subscription
from common.exchanges.exchangeworker import ExchangeWorker
from database.dbmodels.client import ExchangeInfo
from database.models.async_websocket_manager import WebsocketManager
from database.models.ticker import Ticker
from database.models.trade import Trade


# https://binance-docs.github.io/apidocs/futures/en/#aggregate-trade-streams
def _trade_stream(symbol: str):
    return f'{symbol.lower()}@aggTrade'


# https://binance-docs.github.io/apidocs/futures/en/#individual-symbol-ticker-streams
def _ticker_stream(symbol: str):
    return f'{symbol.lower()}@ticker'


# https://binance-docs.github.io/apidocs/futures/en/#websocket-market-streams
class BinanceFuturesTicker(WebsocketManager, ExchangeTicker):
    # _ENDPOINT = 'wss://stream.binancefuture.com' if TESTING else 'wss://fstream.binance.com'
    NAME = 'binance-futures'
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

    async def _subscribe(self, sub: Subscription):
        if sub.channel == Channel.TICKER:
            await self.send_message("SUBSCRIBE", _ticker_stream(sub.kwargs.get("symbol")))
        elif sub.channel is Channel.TRADES:
            await self.send_message("SUBSCRIBE", _trade_stream(sub.kwargs.get("symbol")))

    async def _unsubscribe(self, channel: Channel, **kwargs):
        if channel == Channel.TICKER:
            await self.send_message("UNSUBSCRIBE", _ticker_stream(kwargs.get("symbol")))
        if channel == Channel.TRADES:
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
            await self._callbacks.get(Subscription.get(Channel.TRADES, symbol=msg['s'])).notify(
                Trade(
                    symbol=msg['s'],
                    side='BUY' if msg['m'] else 'SELL',
                    size=msg['q'],
                    price=Decimal(msg['p']),
                    exchange='binance-futures',
                    time=ExchangeWorker.parse_ms_dt(float(msg['E'])),
                    perp=True
                )
            )
        if event == "24hrTicker":
            await self._callbacks.get(Subscription.get(Channel.TICKER, symbol=msg['s'])).notify(
                Ticker(
                    symbol=msg['s'],
                    price=Decimal(msg['c']),
                    src=self.info
                )
            )
