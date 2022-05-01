from __future__ import annotations
import abc
import asyncio
import logging
import time
import urllib.parse
import math
from asyncio import Future
from datetime import datetime, timedelta
from typing import List, Callable, Dict, Tuple, TYPE_CHECKING, Optional, Union
import aiohttp.client
import pytz
from aiohttp import ClientResponse
from typing import NamedTuple

from sqlalchemy import select, desc
from sqlalchemy.orm import joinedload

import balancebot.api.database as db
import balancebot.common.utils as utils
from balancebot.api.database_async import async_session, db_unique, db_all, db_select, db_first
from balancebot.api.dbmodels.execution import Execution
from balancebot.api.dbmodels.trade import Trade, trade_from_execution
import balancebot.collector.usermanager as um

import balancebot.api.dbmodels.balance as db_balance
from balancebot.api.dbmodels.transfer import Transfer
from balancebot.common.config import PRIORITY_INTERVALS
from balancebot.common.enums import Priority
from balancebot.common.messenger import NameSpace, Category, Messenger

from balancebot.api.dbmodels.client import Client


class Cached(NamedTuple):
    url: str
    response: dict
    expires: float


class TaskCache(NamedTuple):
    url: str
    task: Future
    expires: float


class ExchangeWorker:
    _ENDPOINT = ''
    _cache: Dict[str, Cached] = {}

    exchange: str = ''
    required_extra_args: List[str] = []

    def __init__(self, client: Client, session: aiohttp.ClientSession, messenger: Messenger = None, rekt_threshold: float = None):
        self.client = client
        self.client_id = client.id
        self.in_position = True
        self.exchange = client.exchange
        self.messenger = messenger
        self.rekt_threshold = rekt_threshold

        # Client information has to be stored locally because SQL Objects aren't allowed to live in multiple threads
        self._api_key = client.api_key
        self._api_secret = client.api_secret
        self._subaccount = client.subaccount
        self._extra_kwargs = client.extra_kwargs

        self._session = session
        self._last_fetch = datetime.fromtimestamp(0, tz=pytz.UTC)

        self._on_balance = None
        self._on_new_trade = None
        self._on_update_trade = None

    async def get_balance(self,
                          priority: Priority = Priority.MEDIUM,
                          time: datetime = None,
                          force=False,
                          upnl=True) -> Optional[db_balance.Balance]:
        if not time:
            time = datetime.now(tz=pytz.UTC)
        if force or (time - self._last_fetch > timedelta(seconds=PRIORITY_INTERVALS[priority]) and not self.client.rekt_on):
            self._last_fetch = time
            balance = await self._get_balance(time, upnl=upnl)
            if not balance.time:
                balance.time = time
            balance.client_id = self.client_id
            return balance
        elif self.client.rekt_on:
            return db_balance.Balance(amount=0.0, error=None, time=time)
        else:
            return None

    async def get_executions(self,
                             since: datetime) -> List[Execution]:
        return []

    async def intelligent_get_balance(self, keep_errors=False):
        client = await async_session.get(Client, self.client_id)
        if client:

            result = await self.get_balance()

            history = await db_all(
                client.history.order_by(
                    desc(db_balance.Balance.time)
                ).limit(3)
            )

            history_len = len(history)
            latest_balance = None if history_len == 0 else history[history_len - 1]
            if history_len > 2:
                # If balance hasn't changed at all, why bother keeping it?
                if math.isclose(latest_balance.amount, result.amount, rel_tol=1e-06) \
                        and math.isclose(history[history_len - 2].amount, result.amount, rel_tol=1e-06):
                    latest_balance.time = time
            if result.error:
                logging.error(f'Error while fetching {client.id=} balance: {result.error}')
                if keep_errors:
                    return result
            else:
                async_session.add(result)
                if result.amount <= self.rekt_threshold and not client.rekt_on:
                    client.rekt_on = time
                    self.messenger.pub_channel(NameSpace.CLIENT, Category.REKT, channel_id=client.id,
                                               obj={'id': client.id})

            await async_session.commit()
            self.messenger.pub_channel(NameSpace.BALANCE, Category.NEW, channel_id=client.id,
                                       obj=result.id)
            return result

    async def update_transfers(self):
        """

        :param since:
        :return:
        """
        transfers = await self._get_transfers(
            self.client.currently_realized.time if self.client.currently_realized
            else datetime.now(pytz.utc) - timedelta(days=180)
        )
        if transfers:
            transfers.sort(key=lambda transfer: transfer.balance.time)
            to_update: List[db_balance.Balance] = await db_all(self.client.history.statement.filter(
                db_balance.Balance.time > self.client.currently_realized.time
            ))
            # to_update   transfers
            # 1.1. 100
            #             2.1. -100
            # 3.1. 300
            #             4.1.  200
            # 5.1. 500
            # updated:
            # 1.1 100
            # 3.1. 200 (300 - 100)
            # 5.1. 600 (500 - 100 + 200 = 500 + 100)
            cur_offset = transfers[0].amount
            next_transfer = transfers[1] if len(transfers) > 1 else None

            for update in to_update:
                if next_transfer and update.time > next_transfer:
                    cur_offset += next_transfer.amount
                    next_index = transfers.index(next_transfer) + 1
                    next_transfer = transfers[next_index] if len(transfers) > next_index else None
                update.amount += cur_offset

            async_session.add_all(transfers)
        self.client.last_transfer_sync = datetime.now(tz=pytz.utc)
        await async_session.commit()

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> List[Transfer]:
        raise NotImplementedError(f'Exchange {self.exchange} does not implement get_transfers')

    async def synchronize_positions(self,
                                    since: datetime = None,
                                    to: datetime = None):

        latest = await db_first(
            select(Execution).order_by(
                desc(Execution.time)
            ).outerjoin(Trade, Execution.trade_id == Trade.id).filter(
                Trade.client_id == self.client_id,
            )
        )

        executions = await self.get_executions(latest.time if latest else None)

        for execution in executions:
            await self._on_execution(execution, realtime=False)

        if executions:
            # Because all balances after that execution are flawed
            # (calculated with wrong currently_realized)

            update_since = executions[0].time
            to_update = await db_all(
                self.client.history.statement.filter(
                    db_balance.Balance.time > update_since
                )
            )

            execution_iterator = iter(executions)
            execution = next(execution_iterator)

            offset = execution.realized_pnl
            for balance in to_update:
                if execution and balance.time > execution.time:
                    execution = next(execution_iterator)
                    if execution:
                        offset += execution.realized_pnl
                balance.amount += offset

        #db_executions_by_symbol = {
        #    trade.client_id: trade.executions
        #    for trade in await db_all(
        #        select(Trade).filter(
        #            # Execution.time > since,
        #            #Trade.initial.time > since,
#
        #        ),
        #        Trade.executions
        #    )
        #}
        #for symbol in executions_by_symbol:
        #    pass
        await self._update_realized_balance()

    def set_balance_callback(self, callback: Callable):
        if callable(callback):
            self._on_balance = callback

    def set_trade_callback(self, callback: Callable):
        if callable(callback):
            self._on_new_trade = callback

    def set_trade_update_callback(self, callback: Callable):
        if callable(callback):
            self._on_update_trade = callback

    def clear_callbacks(self):
        self._on_balance = self._on_new_trade = self._on_update_trade = None

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    @abc.abstractmethod
    async def _get_balance(self, time: datetime, upnl=True):
        logging.error(f'Exchange {self.exchange} does not implement _get_balance')
        raise NotImplementedError(f'Exchange {self.exchange} does not implement _get_balance')

    @abc.abstractmethod
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        logging.error(f'Exchange {self.exchange} does not implement _sign_request')

    @abc.abstractmethod
    async def _process_response(self, response: ClientResponse):
        logging.error(f'Exchange {self.exchange} does not implement _process_response')

    async def _request(self, method: str, path: str, headers=None, params=None, data=None, sign=True, cache=False,
                       dedupe=False, **kwargs):
        headers = headers or {}
        params = params or {}
        url = self._ENDPOINT + path
        if cache:
            cached = ExchangeWorker._cache.get(url)
            if cached and time.time() < cached.expires:
                return cached.response
        if sign:
            self._sign_request(method, path, headers, params, data)
        async with self._session.request(method, url, headers=headers, params=params, data=data, **kwargs) as resp:
            resp = await self._process_response(resp)
            if cache:
                ExchangeWorker._cache[url] = Cached(
                    url=url,
                    response=resp,
                    expires=time.time() + 5
                )
            return resp

    async def _get(self, path: str, **kwargs):
        return await self._request('GET', path, **kwargs)

    async def _post(self, path: str, **kwargs):
        return await self._request('POST', path, **kwargs)

    async def _put(self, path: str, **kwargs):
        return await self._request('PUT', path, **kwargs)

    def _query_string(self, params: Dict):
        query_string = urllib.parse.urlencode(params)
        return f"?{query_string}" if query_string else ""

    async def _update_realized_balance(self):
        await self.update_transfers()
        balance = await self.get_balance(Priority.FORCE, datetime.now(pytz.utc), upnl=False)
        if balance:
        #balance = await self.intelligent_get_balance(self.client, priority=Priority.FORCE)
        #balance = await um.UserManager().get_client_balance(self.client, priority=Priority.FORCE)
            self.client.currently_realized = balance
            await async_session.commit()

    async def _on_execution(self, execution: Execution, realtime=True):
        active_trade: Trade = await db_unique(
            select(Trade).filter(
                Trade.symbol == execution.symbol,
                Trade.client_id == self.client_id,
                Trade.open_qty > 0.0
            ).options(
                joinedload(Trade.executions),
                joinedload(Trade.initial),
            )
        )
        client: Client = await async_session.get(Client, self.client_id)
        user_manager = um.UserManager()

        self.in_position = True

        def weighted_avg(values: Tuple[float, float], weights: Tuple[float, float]):
            total = weights[0] + weights[1]
            return round(values[0] * (weights[0] / total) + values[1] * (weights[1] / total), ndigits=3)

        if realtime:
            asyncio.create_task(
                self._update_realized_balance()
            )

        if active_trade:
            # Update existing trade
            execution.trade_id = active_trade.id
            async_session.add(execution)

            if execution.side == active_trade.initial.side:
                active_trade.entry = weighted_avg(
                    (active_trade.entry, execution.price),
                    (active_trade.qty, execution.qty)
                )
                active_trade.qty += execution.qty
                active_trade.open_qty += execution.qty
            else:
                new_execution = None
                if execution.qty > active_trade.open_qty:
                    new_execution = Execution(
                        qty=execution.qty - active_trade.open_qty,
                        symbol=execution.symbol,
                        price=execution.price,
                        side=execution.side,
                        time=execution.time
                    )
                    execution.qty = active_trade.open_qty
                    new_trade = trade_from_execution(new_execution)
                    new_trade.client_id = client.id
                    async_session.add(new_trade)
                    if realtime:
                        asyncio.create_task(
                            utils.call_unknown_function(self._on_new_trade, self, new_trade)
                        )
                if execution.qty <= active_trade.qty:
                    if active_trade.exit is None:
                        active_trade.exit = execution.price
                    else:
                        active_trade.exit = weighted_avg((active_trade.exit, execution.price),
                                                         (active_trade.qty - active_trade.open_qty, execution.qty))

                    if math.isclose(active_trade.open_qty, execution.qty, rel_tol=10e-6):
                        active_trade.open_qty = 0.0
                        asyncio.create_task(user_manager.fetch_data([self.client]))
                        if self and not new_execution:
                            self.in_position = False
                    else:
                        active_trade.open_qty -= execution.qty
                    rpnl = active_trade.calc_rpnl()
                    # Only set realized pnl if it isn't given by exchange implementation
                    if execution.realized_pnl is None:
                        execution.realized_pnl = rpnl - active_trade.realized_pnl
                    active_trade.realized_pnl = rpnl
            if realtime:
                asyncio.create_task(
                    utils.call_unknown_function(self._on_update_trade, self, active_trade)
                )
        else:
            trade = trade_from_execution(execution)
            trade.client_id = self.client_id
            async_session.add(trade)
            if realtime:
                asyncio.create_task(
                    user_manager.fetch_data([self.client])
                )
                asyncio.create_task(
                    utils.call_unknown_function(self._on_new_trade, self, trade)
                )

        await async_session.commit()

    @classmethod
    async def get_ticker(self, symbol: str):
        pass

    def _parse_ts(self, ts: Union[int, float]):
        pass

    def __repr__(self):
        return f'<Worker exchange={self.exchange} client_id={self.client_id}>'
