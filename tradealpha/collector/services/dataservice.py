import asyncio
from enum import Enum
from typing import Dict
import sqlalchemy.ext.hybrid
from tradealpha.collector.errors import InvalidExchangeError
from tradealpha.common.exchanges.exchangeticker import ExchangeTicker
from tradealpha.collector.services.baseservice import BaseService
from tradealpha.common import utils
from tradealpha.common.exchanges import EXCHANGE_TICKERS
from tradealpha.common.messenger import NameSpace
from tradealpha.common.models.observer import Observer
from tradealpha.common.models.ticker import Ticker


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

    async def teardown(self):
        for exchange in self._exchanges.values():
            await exchange.disconnect()

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
        self._logger.info(f'Subscribe: {exchange=} {channel=} {kwargs=}')
        ticker = self._exchanges.get(exchange)
        if not ticker:
            self._logger.info(f'Creating ticker for {exchange}')
            ticker_cls = EXCHANGE_TICKERS.get(exchange)
            if ticker_cls and issubclass(ticker_cls, ExchangeTicker):
                ticker = ticker_cls(self._http_session)
                self._exchanges[exchange] = ticker
                await ticker.connect()
            else:
                raise InvalidExchangeError()

        observer = observer or self
        await ticker.subscribe(channel, observer, **kwargs)

    async def unsubscribe(self, exchange: str, channel: Channel, observer: Observer = None, **kwargs):
        self._logger.info(f'Unsubscribe: {exchange=} {channel=} {kwargs=}')

        ticker = self._exchanges.get(exchange)
        if ticker:
            observer = observer or self
            await ticker.unsubscribe(channel, observer, **kwargs)

    async def update(self, ticker: Ticker):
        #ticker: Ticker = new_state[0]
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
