import asyncio
from enum import Enum
from typing import List, Dict

import aiohttp

from balancebot.api.database import session
from balancebot.api.dbmodels.alert import Alert
from balancebot.collector import config
from balancebot.collector.errors import InvalidExchangeError
from balancebot.collector.exchangeticker import ExchangeTicker
from balancebot.common.models.observer import Observer
from balancebot.common.models.singleton import Singleton
from balancebot.common.models.ticker import Ticker


class Channel(Enum):
    TICKER = "ticker"
    TRADES = "trades"


class DataService(Singleton, Observer):

    def init(self, http_session: aiohttp.ClientSession):
        self.alerts: List[Alert] = []
        self._exchanges: Dict[str, ExchangeTicker] = {}
        self._http_session = http_session
        self._tickers: Dict[str, Ticker] = {}

    async def _initialize_alerts(self):
        self.alerts = session.query(Alert).all()

    async def subscribe(self, exchange: str, channel: Channel, observer: Observer = None, **kwargs):

        ticker = self._exchanges.get(exchange)
        if not ticker:
            ticker_cls = config.EXCHANGE_TICKERS.get(exchange)
            if ticker_cls and issubclass(ticker_cls, ExchangeTicker):
                ticker = ticker_cls(self._http_session)
                await ticker.connect()
                self._exchanges[exchange] = ticker
            else:
                raise InvalidExchangeError()

        if observer:
            asyncio.create_task(ticker.subscribe(channel, observer, **kwargs))
        else:
            asyncio.create_task(ticker.subscribe(channel, self, **kwargs))

    async def update(self, *new_state):
        ticker: Ticker = new_state[0]
        self._tickers[f'{ticker.symbol}:{ticker.exchange}'] = ticker

    def get_ticker(self, symbol, exchange):
        ticker = self._tickers.get(f'{symbol}:{exchange}')
        if not ticker:
            asyncio.create_task(self.subscribe(exchange, Channel.TICKER, self, symbol=symbol))
        return self._tickers.get(f'{symbol}:{exchange}')
