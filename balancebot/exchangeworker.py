from __future__ import annotations
import abc
import asyncio
import logging
import time
import urllib.parse
import math
from asyncio import Future
from datetime import datetime, timedelta
from typing import List, Callable, Dict, Tuple, TYPE_CHECKING
import aiohttp.client
import pytz
from aiohttp import ClientResponse
from typing import NamedTuple

from sqlalchemy import select

import balancebot.api.database as db
import balancebot.common.utils as utils
from balancebot.api.database_async import async_session, db_unique
from balancebot.api.dbmodels.execution import Execution
from balancebot.api.dbmodels.trade import Trade, trade_from_execution
import balancebot.collector.usermanager as um

import balancebot.api.dbmodels.balance as db_balance
from balancebot.common.config import PRIORITY_INTERVALS
from balancebot.common.enums import Priority

if TYPE_CHECKING:
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

    def __init__(self, client: Client, session: aiohttp.ClientSession):
        self.client = client
        self.client_id = client.id
        self.in_position = True
        self.exchange = client.exchange

        # Client information has to be stored locally because SQL Objects aren't allowed to live in multiple threads
        self._api_key = client.api_key
        self._api_secret = client.api_secret
        self._subaccount = client.subaccount
        self._extra_kwargs = client.extra_kwargs

        self._session = session
        self._last_fetch = datetime.fromtimestamp(0, tz=pytz.UTC)
        self._identifier = id

        self._on_balance = None
        self._on_new_trade = None
        self._on_update_trade = None

    async def get_balance(self, priority: Priority = Priority.MEDIUM, time: datetime = None, force=False):
        if not time:
            time = datetime.now(tz=pytz.UTC)
        if force or (time - self._last_fetch > timedelta(seconds=PRIORITY_INTERVALS[priority]) and not self.client.rekt_on):
            self._last_fetch = time
            balance = await self._get_balance(time)
            if not balance.time:
                balance.time = time
            balance.client_id = self.client_id
            return balance
        elif self.client.rekt_on:
            return db_balance.Balance(amount=0.0, currency='$', extra_currencies={}, error=None, time=time)
        else:
            return None

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

    def connect(self):
        pass

    @abc.abstractmethod
    async def _get_balance(self, time: datetime):
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
        balance = await um.UserManager().get_client_balance(self.client, priority=Priority.FORCE)
        self.client.currently_realized = balance
        await async_session.commit()

    async def _on_execution(self, execution: Execution):
        active_trade: Trade = await db_unique(
            select(Trade).filter(
                Trade.symbol == execution.symbol,
                Trade.client_id == self.client_id,
                Trade.open_qty > 0.0
            ),
            executions=True,
            initial=True
        )
        #active_trade: Trade = db.session.query(Trade).filter(
        #    Trade.symbol == execution.symbol,
        #    Trade.client_id == self.client_id,
        #    Trade.open_qty > 0.0
        #).first()

        client: client.Client = self.client
        user_manager = um.UserManager()

        self.in_position = True

        def weighted_avg(values: Tuple[float, float], weights: Tuple[float, float]):
            total = weights[0] + weights[1]
            return round(values[0] * (weights[0] / total) + values[1] * (weights[1] / total), ndigits=3)

        if active_trade:
            # Update existing trade
            active_trade.executions.append(execution)

            if execution.side == active_trade.initial.side:
                active_trade.entry = weighted_avg((active_trade.entry, execution.price),
                                                  (active_trade.qty, execution.qty))
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
                    client.trades.append(new_trade)
                    asyncio.create_task(
                        self._update_realized_balance()
                    )
                    asyncio.create_task(
                        utils.call_unknown_function(self._on_new_trade, self, new_trade)
                    )
                if execution.qty <= active_trade.qty:
                    if active_trade.exit is None:
                        active_trade.exit = execution.price
                    else:
                        active_trade.exit = weighted_avg((active_trade.exit, execution.price),
                                                         (active_trade.open_qty, execution.qty))

                    if math.isclose(active_trade.open_qty, execution.qty, rel_tol=10e-6):
                        active_trade.open_qty = 0.0
                        asyncio.create_task(user_manager.fetch_data([self.client]))
                        if self and not new_execution:
                            self.in_position = False
                    else:
                        active_trade.open_qty -= execution.qty
                    active_trade.realized_pnl = active_trade.calc_rpnl()
            asyncio.create_task(
                utils.call_unknown_function(self._on_update_trade, self, active_trade)
            )
        else:
            trade = trade_from_execution(execution)
            client.trades.append(trade)
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

    def __repr__(self):
        return f'<Worker exchange={self.exchange} client_id={self.client_id}>'
