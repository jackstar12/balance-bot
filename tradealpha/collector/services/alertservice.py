import asyncio
from typing import List, Dict

from sqlalchemy import select

from tradealpha.common.dbsync import session
from tradealpha.common.dbasync import async_session, db_del_filter, db_all
from tradealpha.common.dbmodels.alert import Alert
from tradealpha.collector.services.baseservice import BaseService
from tradealpha.collector.services.dataservice import Channel, DataService
from tradealpha.common.enums import Side
from tradealpha.common.messenger import NameSpace as MsgChannel, Category
from tradealpha.common.models.observer import Observer
from tradealpha.common.models.ticker import Ticker


class AlertService(BaseService, Observer):

    def __init__(self, *args, data_service: DataService, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_service = data_service
        self.alerts_by_symbol: Dict[tuple[str, str], List[Alert]] = {}
        self._tickers: Dict[tuple[str, str], Ticker] = {}

    async def initialize_alerts(self):
        alerts = await db_all(select(Alert), session=self._db)

        for alert in alerts:
            await self.data_service.subscribe(alert.exchange, Channel.TICKER, self, symbol=alert.symbol)
            self.add_alert(alert)

        await self._messenger.sub_channel(MsgChannel.ALERT, sub=Category.NEW, callback=self._update)
        await self._messenger.sub_channel(MsgChannel.ALERT, sub=Category.DELETE, callback=self._delete)

    async def run_forever(self):
        # Do nothing, required because otherwise service would finish and the db session would close
        fut = asyncio.get_running_loop().create_future()
        await fut

    def add_alert(self, alert: Alert):
        symbol = (alert.symbol, alert.exchange)
        if symbol not in self.alerts_by_symbol:
            self.alerts_by_symbol[symbol] = []
        self.alerts_by_symbol[symbol].append(alert)

    def remove_alert(self, alert: Alert):
        alerts = self.alerts_by_symbol.get((alert.symbol, alert.exchange))
        if alerts and alert in alerts:
            alerts.remove(alert)

    async def _update(self, data: Dict):
        new: Alert = await self._db.get(Alert, data['id'])
        symbol = (new.symbol, new.exchange)
        ticker = self._tickers.get(symbol)
        if not ticker:
            await self.data_service.subscribe(new.exchange, Channel.TICKER, self, symbol=new.symbol)
            while ticker is None:
                await asyncio.sleep(0.1)
                ticker = self._tickers.get(symbol)
        if new.price > ticker.price:
            new.side = Side.BUY
        else:
            new.side = Side.SELL
        await self._db.commit()
        self.add_alert(new)

    def _delete(self, data: Dict):
        alerts = self.alerts_by_symbol.get((data.get("symbol"), data.get("exchange")))
        for alert in alerts:
            if alert.id == data.get('id'):
                alerts.remove(alert)

    async def update(self, *new_state):
        ticker: Ticker = new_state[0]

        symbol = (ticker.symbol, ticker.exchange)
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
        self._messenger.pub_channel(MsgChannel.ALERT, Category.FINISHED, obj=finished.serialize())
        self.remove_alert(finished)
        await db_del_filter(Alert, id=finished.id)

