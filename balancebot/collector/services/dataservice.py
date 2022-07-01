import asyncio
from enum import Enum
from typing import Dict
import sqlalchemy.ext.hybrid
from balancebot.collector.errors import InvalidExchangeError
from balancebot.common.exchanges.exchangeticker import ExchangeTicker
from balancebot.collector.services.baseservice import BaseService
from balancebot.common import utils
from balancebot.common.exchanges import EXCHANGE_TICKERS
from balancebot.common.messenger import NameSpace
from balancebot.common.models.observer import Observer
from balancebot.common.models.ticker import Ticker


class Channel(Enum):
    TICKER = "ticker"
    TRADES = "trades"


class DataService(BaseService, Observer):
    """
    Provides market data.

    It depends on the exchange having a ``ExchangeTicker``  implementation
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._exchanges: Dict[str, ExchangeTicker] = {}
        self._tickers: Dict[tuple[str, str], Ticker] = {}

    async def run_forever(self):
        await self._update_redis()

    async def subscribe(self, exchange: str, channel: Channel, observer: Observer = None, **kwargs):
        """
        Subscribes to the given ecxhange channel.

            # Will subscribe to BTCUSDT Ticker Messages from binance-futures
            >>> self.subscribe('binance-futures', Channel.TICKER, symbol='BTCUSDT')

        :param exchange: which exchange?
        :param channel: the channel to subscribe to (ticker, trade etc.)
        :param observer: [Optional] will be notified whenever updates arrive
        :param kwargs: will be passed down to the ``ExchangeTicker`` implementation.
        """
        ticker = self._exchanges.get(exchange)
        if not ticker:
            ticker_cls = EXCHANGE_TICKERS.get(exchange)
            if ticker_cls and issubclass(ticker_cls, ExchangeTicker):
                ticker = ticker_cls(self._http_session)
                await ticker.connect()
                self._exchanges[exchange] = ticker
            else:
                raise InvalidExchangeError()

        if observer:
            await ticker.subscribe(channel, observer, **kwargs)
        else:
            await ticker.subscribe(channel, self, **kwargs)

    async def unsubscribe(self, exchange: str, channel: Channel, **kwargs):
        ticker = self._exchanges.get(exchange)
        if ticker:
            await ticker.unsubscribe(channel, )

    async def update(self, *new_state):
        ticker: Ticker = new_state[0]
        self._tickers[(ticker.exchange, ticker.symbol)] = ticker

    def get_ticker(self, symbol, exchange):
        ticker = self._tickers.get((exchange, symbol))
        if not ticker:
            asyncio.create_task(self.subscribe(exchange, Channel.TICKER, self, symbol=symbol))
        return self._tickers.get((exchange, symbol))

    async def _update_redis(self):
        while True:
            for ticker in self._tickers.values():
                await self._redis.set(
                    utils.join_args(NameSpace.TICKER, ticker.exchange, ticker.symbol),
                    str(ticker.price)
                )
            await asyncio.sleep(1)
