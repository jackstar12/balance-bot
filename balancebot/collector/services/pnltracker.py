from sqlalchemy import select
from sqlalchemy.inspection import inspect
import asyncio
import time
from datetime import datetime
from typing import Dict

import aiohttp
import pytz

from balancebot.api.database import session
from balancebot.api.database_async import async_session, db_all, db_select_all
from balancebot.api.dbmodels.balance import Balance
from balancebot.api.dbmodels.trade import Trade
from balancebot.collector.services.dataservice import DataService, Channel
from balancebot.common.messenger import Category, SubCategory
from balancebot.common.messenger import Messenger
from balancebot.common.models.observer import Observer
from balancebot.common.models.singleton import Singleton


def update_balance(balance: Balance, client_id: int, amount: float, cmp_func):
    if not balance:
        new = Balance(
            client_id=client_id,
            amount=amount,
            time=datetime.now(tz=pytz.utc),
            currency='$'
        )
        async_session.add(new)
        return new, True
    elif cmp_func(amount, balance.amount):
        balance.amount = amount
        balance.time = datetime.now(pytz.utc)
        return balance, True
    return balance, False



class PnlService(Singleton):

    def init(self, http_session: aiohttp.ClientSession):
        self.data_service = DataService(http_session)
        self.messanger = Messenger()
        self._trades_by_id: Dict[int, Trade] = {}

    async def _initialize_positions(self):
        trades = await db_all(select(Trade), Trade.client)

        for trade in trades:
            if trade.is_open:
                await self.data_service.subscribe(trade.client.exchange, Channel.TICKER, symbol=trade.symbol)
                self._trades_by_id[trade.id] = trade

        self.messanger.sub_channel(Category.TRADE, sub=SubCategory.UPDATE, callback=self._on_trade_update, pattern=True)
        self.messanger.sub_channel(Category.TRADE, sub=SubCategory.NEW, callback=self._on_trade_update, pattern=True)
        self.messanger.sub_channel(Category.TRADE, sub=SubCategory.FINISHED, callback=self._on_trade_delete,
                                   pattern=True)

    def _on_trade_update(self, data: Dict):
        trade = session.get(Trade, data.get('id'))
        if trade:
            self._trades_by_id[trade.id] = trade

    def _on_trade_delete(self, data: Dict):
        self._trades_by_id.pop(data.get('id'), None)

    async def run_forever(self):
        await self._initialize_positions()
        while True:
            ts = time.time()
            changes = False
            for trade in self._trades_by_id.values():
                ticker = self.data_service.get_ticker(trade.symbol, trade.client.exchange)
                if ticker:
                    upnl = trade.calc_upnl(ticker.price)
                    trade.max_upnl, changes = update_balance(trade.max_upnl, trade.client_id, upnl, float.__ge__)
                    trade.min_upnl, changes = update_balance(trade.min_upnl, trade.client_id, upnl, float.__le__)
                    self.messanger.pub_channel(Category.TRADE, SubCategory.UPNL, channel_id=trade.client_id,
                                               obj={'id': trade.id, 'upnl': upnl})
            if changes:
                await async_session.commit()
            await asyncio.sleep(3 - (time.time() - ts))
