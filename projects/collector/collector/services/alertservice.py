import asyncio
from typing import List, Dict

from sqlalchemy import select

from common.exchanges.exchangeticker import Subscription
from database.redis import TableNames
from database.dbasync import db_all
from database.dbmodels.alert import Alert
from collector.services.baseservice import BaseService
from common.exchanges.channel import Channel
from collector.services.dataservice import DataService, ExchangeInfo
from database.enums import Side
from common.messenger import Category
from database.models.observer import Observer
from database.models.ticker import Ticker


class AlertService(BaseService, Observer):

    def __init__(self, *args, data_service: DataService, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_service = data_service
        self.alerts_by_symbol: Dict[tuple[str, str], List[Alert]] = {}
        self._tickers: Dict[tuple[str, str], Ticker] = {}

    async def initialize_alerts(self):
        alerts = await db_all(select(Alert), session=self._db)

        for alert in alerts:
            await self.data_service.subscribe(
                ExchangeInfo(name=alert.src, sandbox=False),
                Subscription.get(Channel.TICKER, symbol=alert.symbol),
                self
            )
            self.add_alert(alert)

        await self._messenger.bulk_sub(TableNames.ALERT, {
            Category.NEW: self._update,
            Category.DELETE: self._delete
        })

    def add_alert(self, alert: Alert):
        symbol = (alert.symbol, alert.exchange)
        if symbol not in self.alerts_by_symbol:
            self.alerts_by_symbol[symbol] = []
        self.alerts_by_symbol[symbol].append(alert)

    def _remove_alert(self, alert: Alert):
        alerts = self.alerts_by_symbol.get((alert.symbol, alert.exchange))
        if alerts and alert in alerts:
            alerts.remove(alert)

    async def _update(self, data: Dict):
        new: Alert = await self._db.get(Alert, data['id'])
        symbol = (new.symbol, new.exchange)
        ticker = self._tickers.get(symbol)
        if not ticker:
            await self.data_service.subscribe(
                ExchangeInfo(name=new.exchange, sandbox=False),
                Subscription.get(Channel.TICKER, symbol=new.symbol),
                self
            )
            while ticker is None:
                await asyncio.sleep(0.1)
                ticker = self._tickers.get(symbol)
        if new.price > ticker.price:
            new.side = Side.BUY
        else:
            new.side = Side.SELL
        await self._db.commit()
        self.add_alert(new)

    async def _delete(self, data: Dict):
        alert = await self._db.get(Alert, data['id'])
        self._remove_alert(alert)

    async def update(self, *new_state):
        ticker: Ticker = new_state[0]

        symbol = (ticker.symbol, ticker.src)
        self._tickers[symbol] = ticker

        alerts = self.alerts_by_symbol.get(symbol)
        if alerts:
            for alert in self.alerts_by_symbol.get(symbol):
                if alert.side == Side.BUY:
                    if ticker.price > alert.price:
                        await self._finish_alert(alert)
                elif alert.side == Side.SELL:
                    if ticker.price < alert.price:
                        await self._finish_alert(alert)

            await self._db.commit()

    async def _finish_alert(self, finished: Alert):
        self._messenger.pub_instance(finished, Category.FINISHED)
        self._remove_alert(finished)
        await self._db.delete(finished)
