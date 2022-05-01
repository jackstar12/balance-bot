from typing import List, Dict

import aiohttp
from sqlalchemy import select

from balancebot.api.database import session
from balancebot.api.database_async import async_session, db_del_filter, db_all
from balancebot.api.dbmodels.alert import Alert
from balancebot.collector.services.baseservice import BaseService
from balancebot.collector.services.dataservice import DataService, Channel
from balancebot.common.messenger import NameSpace as MsgChannel, Category
from balancebot.common.messenger import Messenger
from balancebot.common.models.observer import Observer
from balancebot.common.models.singleton import Singleton
from balancebot.common.models.ticker import Ticker


class AlertService(BaseService, Observer):

    def __init__(self, *args, data_service, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_service = data_service
        self.alerts_by_symbol: Dict[str, List[Alert]] = {}
        self._tickers: Dict[str, Ticker] = {}

    async def initialize_alerts(self):
        alerts = await db_all(select(Alert))

        for alert in alerts:
            await self.data_service.subscribe('ftx', Channel.TICKER, self, symbol=alert.symbol)
            self.add_alert(alert)

        self._messenger.sub_channel(MsgChannel.ALERT, sub=Category.NEW, callback=self._update)
        self._messenger.sub_channel(MsgChannel.ALERT, sub=Category.DELETE, callback=self._delete)

    def add_alert(self, alert: Alert):
        symbol = f'{alert.symbol}:{alert.exchange}'
        if symbol not in self.alerts_by_symbol:
            self.alerts_by_symbol[symbol] = []
        self.alerts_by_symbol[symbol].append(alert)

    def remove_alert(self, alert: Alert):
        symbol = f'{alert.symbol}:{alert.exchange}'
        alerts = self.alerts_by_symbol.get(symbol)
        if alerts and alert in alerts:
            alerts.remove(alert)

    def _update(self, data: Dict):
        new: Alert = session.query(Alert).filter_by(id=data.get('id')).first()
        symbol = f'{new.symbol}:{new.exchange}'
        if new.price > self._tickers.get(symbol).price:
            new.side = 'up'
        else:
            new.side = 'down'
        self.add_alert(new)

    def _delete(self, data: Dict):
        symbol = f'{data.get("symbol")}:{data.get("exchange")}'
        alerts = self.alerts_by_symbol.get(symbol)
        for alert in alerts:
            if alert.id == data.get('id'):
                alerts.remove(alert)

    async def update(self, *new_state):
        ticker: Ticker = new_state[0]

        symbol = f'{ticker.symbol}:{ticker.exchange}'
        self._tickers[symbol] = ticker

        alerts = self.alerts_by_symbol.get(symbol)
        if alerts:
            changes = False
            for alert in self.alerts_by_symbol.get(symbol):
                if alert.side == 'up':
                    if ticker.price > alert.price:
                        await self._finish_alert(alert)
                        changes = True
                elif alert.side == 'down':
                    if ticker.price < alert.price:
                        await self._finish_alert(alert)
                        changes = True

            if changes:
                await async_session.commit()

    async def _finish_alert(self, finished: Alert):
        self._messenger.pub_channel(MsgChannel.ALERT, Category.FINISHED, obj=await finished.serialize())
        self.remove_alert(finished)
        await db_del_filter(Alert, id=finished.id)

