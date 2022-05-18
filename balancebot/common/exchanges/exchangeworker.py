from __future__ import annotations
import abc
import asyncio
import itertools
import json
import logging
import time
import urllib.parse
import math
from asyncio import Future, Task
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import List, Callable, Dict, Tuple, Optional, Union, Set, Type, Iterator, Any
import aiohttp.client
import pytz
from aiohttp import ClientResponse, ClientResponseError
from typing import NamedTuple
from asyncio.queues import PriorityQueue
from dataclasses import dataclass

from sqlalchemy import select, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

import balancebot.common.utils as utils
from balancebot.common import customjson
from balancebot.common.database_async import async_session, db_unique, db_all, db_first
from balancebot.common.dbmodels.amountmixin import AmountMixin
from balancebot.common.dbmodels.execution import Execution
from balancebot.common.dbmodels.trade import Trade, trade_from_execution

import balancebot.common.dbmodels.balance as db_balance
from balancebot.common.dbmodels.transfer import Transfer, RawTransfer, TransferType
from balancebot.common.config import PRIORITY_INTERVALS
from balancebot.common.enums import Priority, ExecType, Side
from balancebot.common.errors import RateLimitExceeded, ExchangeUnavailable, ExchangeMaintenance, ResponseError
from balancebot.common.messenger import NameSpace, Category, Messenger

from balancebot.common.dbmodels.client import Client
from typing import TYPE_CHECKING

from balancebot.common.models.ohlc import OHLC

if TYPE_CHECKING:
    from balancebot.common.dbmodels.balance import Balance


logger = logging.getLogger(__name__)


def weighted_avg(values: Tuple[float, float], weights: Tuple[float, float]):
    total = weights[0] + weights[1]
    return round(values[0] * (weights[0] / total) + values[1] * (weights[1] / total), ndigits=3)


class Cached(NamedTuple):
    url: str
    response: dict
    expires: float


class TaskCache(NamedTuple):
    url: str
    task: Future
    expires: float


class RequestItem(NamedTuple):
    priority: Priority
    future: Future
    cache: bool
    weight: Optional[int]
    request: Request

    def __gt__(self, other):
        return self.priority.value > other.priority.value

    def __lt__(self, other):
        return self.priority.value < other.priority.value


class State(Enum):
    OK = 1
    RATE_LIMIT = 2
    MAINTANENANCE = 3
    OFFLINE = 4


class Request(NamedTuple):
    method: str
    url: str
    path: str
    headers: Optional[Dict]
    params: Optional[Dict]
    json: Optional[Dict]


def create_limit(interval_seconds: int, max_amount: int, default_weight: int):
    return Limit(
        interval_seconds,
        max_amount,
        max_amount,
        default_weight,
        interval_seconds / max_amount
    )


@dataclass
class Limit:
    interval_seconds: int
    max_amount: int
    amount: float
    default_weight: int
    refill_rate_seconds: float
    last_ts: float = 0

    def validate(self, weight: int = None):
        return self.amount < (weight or self.default_weight)

    def refill(self, ts: float):
        self.amount = min(
            self.amount + (ts - self.last_ts) * self.refill_rate_seconds,
            self.max_amount
        )
        self.last_ts = ts

    def sleep_for_weight(self, weight: int = None):
        return asyncio.sleep((weight or self.default_weight) / self.refill_rate_seconds)


class ExchangeWorker:

    state = State.OK
    exchange: str = ''
    required_extra_args: Set[str] = set()

    _ENDPOINT = ''
    _cache: Dict[str, Cached] = {}

    # Networking
    _response_result = ''
    _request_queue: PriorityQueue[RequestItem] = None
    _response_error = ''
    _request_task: Task = None
    _session = None

    # Rate Limiting
    _limits = [
        create_limit(interval_seconds=60, max_amount=60, default_weight=1)
    ]

    def __init__(self, client: Client,
                 session: aiohttp.ClientSession,
                 messenger: Messenger = None,
                 rekt_threshold: float = None,
                 execution_dedupe_seconds: float = 5e-3):

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
        self._execution_dedupe_delay = execution_dedupe_seconds
        # dummy future
        self._waiter = Future()

        cls = self.__class__

        if cls._session is None or cls._session.closed:
            cls._session = session

        if cls._request_task is None:
            cls._request_task = asyncio.create_task(cls._request_handler())

        if cls._request_queue is None:
            cls._request_queue = PriorityQueue()

    async def get_balance(self,
                          priority: Priority = Priority.MEDIUM,
                          date: datetime = None,
                          force=False,
                          upnl=True,
                          return_cls: Type[AmountMixin] = None) -> Optional[Balance]:
        if not date:
            date = datetime.now(tz=pytz.UTC)
        if force or (date - self._last_fetch > timedelta(seconds=PRIORITY_INTERVALS[priority]) and not self.client.rekt_on):
            self._last_fetch = date
            try:
                balance = await self._get_balance(date, upnl=upnl)
            except ResponseError as e:
                return db_balance.Balance(
                    amount=0,
                    time=date,
                    error=e.human
                )
            if not balance.time:
                balance.time = date
            balance.client_id = self.client_id
            balance.total_transfered = getattr(
                self.client.currently_realized, 'total_transfered', Decimal(0)
            )
            return balance
        elif self.client.rekt_on:
            return db_balance.Balance(amount=0.0, error=None, time=date)
        else:
            return None

    async def _get_executions(self,
                              since: datetime) -> List[Execution]:
        return []

    async def get_executions(self,
                             since: datetime = None,
                             db_session: AsyncSession = None) -> Tuple[Dict[str, List[Execution]], List[Execution]]:
        grouped = {}
        since = since or self.client.last_execution_sync
        self.client.last_execution_sync = datetime.now(pytz.utc)
        transfers, execs = await asyncio.gather(
            self.update_transfers(since, db_session),
            self._get_executions(since)
        )
        for transfer in transfers:
            if not self._usd_like(transfer.coin) and transfer.coin:
                raw_amount = transfer.extra_currencies[transfer.coin]
                transfer.execution = Execution(
                    symbol=self._symbol(transfer.coin),
                    qty=abs(raw_amount),
                    price=transfer.amount / raw_amount,
                    side=Side.BUY if transfer.type == TransferType.DEPOSIT else Side.SELL,
                    time=transfer.time,
                    type=ExecType.TRANSFER
                )
                execs.append(transfer.execution)
        execs.sort(key=lambda e: e.time)
        for execution in execs:
            if execution.symbol not in grouped:
                grouped[execution.symbol] = []
            grouped[execution.symbol].append(execution)
        return grouped, execs

    async def intelligent_get_balance(self,
                                      keep_errors=False,
                                      commit=True,
                                      date: datetime = None,
                                      db_session: AsyncSession = None) -> Optional["Balance"]:
        """
        Fetch the clients balance, only saving if it makes sense to do so.
        :param db_session:
        database session to ues
        :param date:
        :param keep_errors:
        whether to return the balance if it resulted in an error
        :param commit:
        whether to not commit the new balance. Can be used if calling this function
        multiple times.
        NOTE: after calling all you should also publish the balances accordingly
        :return:
        new balance object
        """
        db_session = db_session or async_session
        client: Client = await db_session.get(
            Client,
            self.client_id,
            options=(selectinload(Client.recent_history),)  # Needs to be an iterable
        )
        if client:
            date = date or datetime.now(pytz.utc)
            result = await self.get_balance(date=date)

            if not result:
                return

            history = client.recent_history

            history_len = len(history)
            latest_balance = None if history_len == 0 else history[history_len - 1]
            if history_len > 2:
                # If balance hasn't changed at all, why bother keeping it?
                if latest_balance == result and history[history_len - 2] == result:
                    latest_balance.time = date
                    return None
            if result.error:
                logger.error(f'Error while fetching {client.id=} balance: {result.error}')
                if keep_errors:
                    return result
            else:
                if result.amount <= self.rekt_threshold and not client.rekt_on:
                    client.rekt_on = time
                    self.messenger.pub_channel(NameSpace.CLIENT, Category.REKT, channel_id=client.id,
                                               obj={'id': client.id})
            if commit:
                db_session.add(result)
                await db_session.commit()
                self.messenger.pub_channel(NameSpace.BALANCE, Category.NEW, channel_id=client.id,
                                           obj={'id': result.id})
            return result

    async def get_transfers(self, since: datetime = None) -> List[Transfer]:
        if not since:
            since = (
                self.client.last_transfer_sync or datetime.now(pytz.utc) - timedelta(days=365)
            )
        raw_transfers = await self._get_transfers(since)
        if raw_transfers:
            raw_transfers.sort(key=lambda transfer: transfer.time)
        return [
            Transfer(
                amount=await self._convert_to_usd(raw_transfer.amount, raw_transfer.coin, raw_transfer.time),
                time=raw_transfer.time,
                extra_currencies={raw_transfer.coin: raw_transfer.amount}
                if not self._usd_like(raw_transfer.coin) else None,
                coin=raw_transfer.coin,
                client_id=self.client_id
            )
            for raw_transfer in raw_transfers
        ]

    async def update_transfers(self, since: datetime = None, db_session: AsyncSession = None) -> List[Transfer]:
        db_session = db_session or async_session
        transfers = await self.get_transfers(since)
        self.client.last_transfer_sync = datetime.now(tz=pytz.utc)
        if transfers:
            to_update: List[db_balance.Balance] = await db_all(
                self.client.history.statement.filter(
                    db_balance.Balance.time > transfers[0].time
                ),
                session=db_session
            )
            """
            to_update   transfers
            1.1. 100
                        2.1. -100
            3.1. 300
                        4.1.  200
            5.1. 500
            updated:
            1.1 100
            3.1. 200 (300 - 100)
            5.1. 600 (500 - 100 + 200 = 500 + 100)
            """
            transfer_iter = iter(transfers)
            next_transfer = next(transfer_iter, None)
            cur_offset = Decimal(0)
            for update in to_update:
                if next_transfer and update.time > next_transfer.time:
                    cur_offset += next_transfer.amount
                    next_transfer = next(transfer_iter, None)
                update.total_transfered += cur_offset

        db_session.add_all(transfers)
        await db_session.commit()
        return transfers

    async def synchronize_positions(self,
                                    since: datetime = None,
                                    to: datetime = None,
                                    db_session: AsyncSession = None):

        self.client = await db_session.get(
            Client,
            self.client_id,
            options=(
                selectinload(Client.open_trades).selectinload(Trade.executions)
            )
        )
        since = self.client.last_execution_sync

        check_executions = await db_all(
            select(Execution).order_by(
                asc(Execution.time)
            ).outerjoin(
                Execution.trade
            ).filter(
                Trade.client_id == self.client_id,
                Execution.time > since if since else True
            ),
            session=db_session
        )

        executions_by_symbol, all_executions = await self.get_executions(since, db_session=db_session)

        valid_until = since

        for execution, check in zip(check_executions, all_executions):
            if execution.time != check.time:
                for trade in self.client.open_trades:
                    await trade.reverse_to(since, db_session=db_session, commit=False)
                break
            else:
                valid_until = execution.time
        await db_session.commit()

        if executions_by_symbol:
            for symbol, executions in executions_by_symbol.items():
                if not symbol:
                    continue
                exec_iter = iter(executions)
                to_exec = next(exec_iter, None)

                # In order to avoid unnecesary OHLC data between trades being fetched
                # we preflight the executions in a way where the executions which
                # form a trade can be extracted.

                while to_exec:
                    if to_exec.time > valid_until:
                        current_executions = [to_exec]
                        open_qty = to_exec.effective_qty

                        while open_qty != 0 and to_exec:
                            to_exec = next(exec_iter, None)
                            if to_exec:
                                current_executions.append(to_exec)
                                open_qty += to_exec.effective_qty

                        if open_qty:
                            # If the open_qty is not 0 there is an active trade going on
                            # -> needs to be published (unlike others which are historical)
                            pass

                        ohlc_data = await self._get_ohlc(
                            symbol,
                            since=current_executions[0].time,
                            to=current_executions[len(current_executions) - 1].time
                        )

                        timeline = sorted(ohlc_data + current_executions, key=lambda item: item.time)
                        current_trade = None
                        for item in timeline:
                            if isinstance(item, Execution):
                                current_trade = await self._on_execution(item, realtime=False, db_session=db_session)
                            elif isinstance(item, OHLC) and current_trade:
                                current_trade.update_pnl(
                                    item.open,
                                    realtime=False,
                                    commit=False,
                                    now=item.time
                                )
                        await db_session.commit()
                    to_exec = next(exec_iter, None)

        await self._update_realized_balance()

    async def _convert_to_usd(self, amount: float, coin: str, date: datetime):
        if self._usd_like(coin):
            return amount

    async def _get_ohlc(self, market: str, since: datetime, to: datetime, resolution_s: int = None, limit: int = None) -> List[OHLC]:
        pass

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

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> List[RawTransfer]:
        logger.warning(f'Exchange {self.exchange} does not implement get_transfers')
        return []

    async def _update_realized_balance(self):
        self._waiter = asyncio.ensure_future(asyncio.sleep(self._execution_dedupe_delay))
        await self._waiter
        await self.update_transfers()
        balance = await self.get_balance(
            Priority.FORCE,
            datetime.now(pytz.utc),
            upnl=False
        )
        if balance:
            self.client.currently_realized = balance
            await async_session.commit()

    async def _on_execution(self, execution: Execution, realtime=True, db_session: AsyncSession = None) -> Trade:

        db_session = db_session or async_session

        if realtime and not self._waiter.done():
            self._waiter.cancel()

        active_trade: Trade = await db_unique(
            select(Trade).filter(
                Trade.symbol == execution.symbol,
                Trade.client_id == self.client_id,
                Trade.open_qty > 0.0
            ),
            Trade.executions,
            Trade.initial,
            session=db_session
        )

        self.in_position = True

        if realtime:
            asyncio.create_task(
                self._update_realized_balance()
            )

        if active_trade:
            # Update existing trade
            execution.trade_id = active_trade.id
            db_session.add(execution)

            if execution.type == ExecType.TRANSFER:
                active_trade.transferred_qty += execution.qty
                active_trade.qty += execution.qty
            elif execution.side == active_trade.initial.side:
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
                    new_trade.client_id = self.client_id
                    db_session.add(new_trade)

                    asyncio.create_task(
                        utils.call_unknown_function(self._on_new_trade, self, new_trade)
                    )
                if execution.qty <= active_trade.open_qty:
                    if active_trade.exit is None:
                        active_trade.exit = execution.price
                    else:
                        active_trade.exit = weighted_avg((active_trade.exit, execution.price),
                                                         (active_trade.qty - active_trade.open_qty, execution.qty))

                    active_trade.open_qty -= execution.qty
                    if active_trade.open_qty.is_zero():
                        if self and not new_execution:
                            self.in_position = False
                    rpnl = active_trade.calc_rpnl()
                    # Only set realized pnl if it isn't given by exchange implementation
                    if execution.realized_pnl is None:
                        execution.realized_pnl = rpnl - (active_trade.realized_pnl or Decimal('0'))
                    active_trade.realized_pnl = rpnl
            asyncio.create_task(
                utils.call_unknown_function(self._on_update_trade, self, active_trade)
            )
        else:
            active_trade = trade_from_execution(execution)
            active_trade.client_id = self.client_id
            db_session.add(active_trade)
            asyncio.create_task(
                utils.call_unknown_function(self._on_new_trade, self, active_trade)
            )

        await db_session.commit()

        return active_trade

    @abc.abstractmethod
    async def _get_balance(self, time: datetime, upnl=True):
        logger.error(f'Exchange {self.exchange} does not implement _get_balance')
        raise NotImplementedError(f'Exchange {self.exchange} does not implement _get_balance')

    @abc.abstractmethod
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        logger.error(f'Exchange {self.exchange} does not implement _sign_request')

    @abc.abstractmethod
    def _set_rate_limit_parameters(self, response: ClientResponse):
        pass

    @classmethod
    def _check_for_error(cls, response_json: Dict, response: ClientResponse):
        pass

    @classmethod
    @abc.abstractmethod
    async def _process_response(cls, response: ClientResponse) -> dict:
        response_json = await response.json(loads=customjson.loads)
        try:
            response.raise_for_status()
        except ClientResponseError as e:
            logger.error(f'{e}\n{response_json=}\n{response.reason=}')

            error = ''
            if response.status == 400:
                error = "400 Bad Request. This is probably a bug in the test_bot, please contact dev"
            elif response.status == 401:
                error = f"401 Unauthorized ({response.reason}). You might want to check your API access"
            elif response.status == 403:
                error = f"403 Access Denied ({response.reason}). You might want to check your API access"
            elif response.status == 404:
                error = f"404 Not Found. This is probably a bug in the test_bot, please contact dev"
            elif response.status == 429:
                raise RateLimitExceeded(
                    root_error=e,
                    human="429 Rate Limit Exceeded. Please try again later."
                )
            elif 500 <= response.status < 600:
                raise ExchangeUnavailable(
                    root_error=e,
                    human=f"{response.status} Problem or Maintenance on {cls.exchange} servers."
                )

            raise ResponseError(
                root_error=e,
                human=error
            )

        cls._check_for_error(response_json, response)

        # OK
        if response.status == 200:
            if cls._response_result:
                return response_json[cls._response_result]
            return response_json

    @classmethod
    def set_weights(cls, weight: int, response: ClientResponse):
        for limit in cls._limits:
            limit.amount -= weight or limit.default_weight

    @classmethod
    async def _request_handler(cls):
        while True:
            try:
                item = await cls._request_queue.get()
                request = item.request

                ts = time.monotonic()

                # Provide some basic limiting by default
                for limit in cls._limits:
                    limit.refill(ts)
                    if limit.validate(item.weight):
                        await limit.sleep_for_weight(item.weight)
                        ts = time.monotonic()
                        limit.refill(ts)

                async with cls._session.request(request.method,
                                                request.url,
                                                params=request.params,
                                                headers=request.headers,
                                                json=request.json) as resp:

                    try:
                        cls.set_weights(item.weight, resp)
                        resp = await cls._process_response(resp)

                        if item.cache:
                            cls._cache[item.request.url] = Cached(
                                url=item.request.url,
                                response=resp,
                                expires=time.time() + 5
                            )

                        item.future.set_result(resp)
                    except RateLimitExceeded as e:
                        cls.state = State.RATE_LIMIT
                        if e.retry_ts:
                            await asyncio.sleep(time.monotonic() - e.retry_ts)
                    except ExchangeUnavailable as e:
                        cls.state = State.OFFLINE
                    except ExchangeMaintenance as e:
                        cls.state = State.MAINTANENANCE
                    except Exception as e:
                        logger.exception(f'Exception while execution request {item}')
                        item.future.set_exception(e)
                    finally:
                        cls._request_queue.task_done()

            except Exception:
                logger.exception('why')

    async def _request(self,
                       method: str, path: str,
                       headers=None, params=None, data=None,
                       sign=True, cache=False,
                       endpoint=None, dedupe=False, weight=None,
                       **kwargs):
        url = (endpoint or self._ENDPOINT) + path
        request = Request(
            method,
            url,
            path,
            headers or {},
            params or {},
            data
        )
        if cache:
            cached = ExchangeWorker._cache.get(url)
            if cached and time.time() < cached.expires:
                return cached.response
        if sign:
            self._sign_request(request.method, request.path, request.headers, request.params, request.json)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self.__class__._request_queue.put(
            RequestItem(
                priority=Priority.MEDIUM,
                future=future,
                cache=cache,
                weight=None,
                request=request
            )
        )
        return await future

    def _get(self, path: str, **kwargs):
        return self._request('GET', path, **kwargs)

    def _post(self, path: str, **kwargs):
        return self._request('POST', path, **kwargs)

    def _put(self, path: str, **kwargs):
        return self._request('PUT', path, **kwargs)

    def _usd_like(self, coin: str):
        return coin in ('USD', 'USDT', 'USDC', 'BUSD')

    def _symbol(self, coin: str):
        return f'{coin}/{self.client.currency or "USD"}'

    def _query_string(self, params: Dict):
        query_string = urllib.parse.urlencode(params)
        return f"?{query_string}" if query_string else ""

    def _parse_ts(self, ts: Union[int, float]):
        pass

    def _ts_for_ccxt(self, datetime: datetime):
        return int(datetime.timestamp() * 1000)

    def _date_from_ccxt(self, ts):
        return datetime.fromtimestamp(ts / 1000, pytz.utc)

    def __repr__(self):
        return f'<Worker exchange={self.exchange} client_id={self.client_id}>'
