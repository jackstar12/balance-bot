from typing import List, Dict

import aiohttp

from balancebot.api.database import session
from balancebot.api.database_async import async_session, db_del_filter
from balancebot.api.dbmodels.alert import Alert
from balancebot.collector.services.dataservice import DataService, Channel
from balancebot.common.messenger import Category as MsgChannel, SubCategory
from balancebot.common.messenger import Messenger
from balancebot.common.models.observer import Observer
from balancebot.common.models.singleton import Singleton
from balancebot.common.models.ticker import Ticker


class AlertService(Singleton, Observer):

    def init(self, http_session: aiohttp.ClientSession):

        self.data_service = DataService(http_session)
        self.messanger = Messenger()
        self.alerts_by_symbol: Dict[str, List[Alert]] = {}
        self._tickers: Dict[str, Ticker] = {}

    async def initialize_alerts(self):
        alerts = session.query(Alert).all()

        for alert in alerts:
            await self.data_service.subscribe('ftx', Channel.TICKER, self, symbol=alert.symbol)
            self.add_alert(alert)

        self.messanger.sub_channel(MsgChannel.ALERT, sub=SubCategory.NEW, callback=self._update)
        self.messanger.sub_channel(MsgChannel.ALERT, sub=SubCategory.DELETE, callback=self._delete)

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
        self.messanger.pub_channel(MsgChannel.ALERT, SubCategory.FINISHED, obj=finished.serialize())
        self.remove_alert(finished)
        await db_del_filter(Alert, id=finished.id)

