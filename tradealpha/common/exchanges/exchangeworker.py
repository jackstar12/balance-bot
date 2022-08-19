from __future__ import annotations
import abc
import asyncio
import itertools
import logging
import time
import urllib.parse
from asyncio import Future, Task
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import List, Callable, Dict, Tuple, Optional, Union, Set
import aiohttp.client
import pytz
from aiohttp import ClientResponse, ClientResponseError
from typing import NamedTuple
from asyncio.queues import PriorityQueue
from dataclasses import dataclass

from sqlalchemy import select, desc, asc, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, sessionmaker

import tradealpha.common.utils as utils
from tradealpha.common.models.miscincome import MiscIncome
from tradealpha.common.redis.client import ClientSpace
from tradealpha.common import customjson
from tradealpha.common.dbasync import db_unique, db_all
from tradealpha.common.dbmodels.execution import Execution
from tradealpha.common.dbmodels.pnldata import PnlData
from tradealpha.common.dbmodels.trade import Trade, trade_from_execution

from tradealpha.common.dbmodels.transfer import Transfer, RawTransfer, TransferType
from tradealpha.common.config import PRIORITY_INTERVALS
from tradealpha.common.enums import Priority, ExecType, Side
from tradealpha.common.errors import RateLimitExceeded, ExchangeUnavailable, ExchangeMaintenance, ResponseError, \
    InvalidClientError, ClientDeletedError
from tradealpha.common.messenger import NameSpace, Category, Messenger

from tradealpha.common.dbmodels.client import Client
from typing import TYPE_CHECKING

from tradealpha.common.models.ohlc import OHLC
from tradealpha.common.utils import combine_time_series

if TYPE_CHECKING:
    from tradealpha.common.dbmodels.balance import Balance

import tradealpha.common.dbmodels.balance as db_balance

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
    source: Client


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
    supports_extended_data = False
    state = State.OK
    exchange: str = ''
    required_extra_args: Set[str] = set()

    _ENDPOINT: str
    _SANDBOX_ENDPOINT: str
    _cache: Dict[str, Cached] = {}

    # Networking
    _response_result = ''
    _request_queue: PriorityQueue[RequestItem] = None
    _response_error = ''
    _request_task: Task = None
    _http = None

    # Rate Limiting
    _limits = [
        create_limit(interval_seconds=60, max_amount=60, default_weight=1)
    ]

    def __init__(self,
                 client: Client,
                 http_session: aiohttp.ClientSession,
                 db_maker: sessionmaker,
                 messenger: Messenger = None,
                 rekt_threshold: float = None,
                 execution_dedupe_seconds: float = 5e-3, ):

        self.client_id = client.id
        self.in_position = True
        self.exchange = client.exchange
        self.messenger = messenger
        self.rekt_threshold = rekt_threshold
        self.client: Client = client
        self.db_lock = asyncio.Lock()
        self.db_maker = db_maker

        # Client information has to be stored locally because SQL Objects aren't allowed to live in multiple threads
        self._api_key = client.api_key
        self._api_secret = client.api_secret
        self._subaccount = client.subaccount
        self._extra_kwargs = client.extra_kwargs

        self._http = http_session
        self._last_fetch = datetime.fromtimestamp(0, tz=pytz.UTC)

        self._on_balance = None
        self._on_new_trade = None
        self._on_update_trade = None
        self._execution_dedupe_delay = execution_dedupe_seconds
        self._pending_execs: deque[Execution] = deque()
        # dummy future
        self._waiter = Future()

        cls = self.__class__

        if cls._http is None or cls._http.closed:
            cls._http = http_session

        if cls._request_task is None:
            cls._request_task = asyncio.create_task(cls._request_handler())

        if cls._request_queue is None:
            cls._request_queue = PriorityQueue()

        self._logger = logging.getLogger(__name__ + f' {self.exchange} - {self.client_id}')

    async def get_balance(self,
                          priority: Priority = Priority.MEDIUM,
                          date: datetime = None,
                          force=False,
                          upnl=True) -> Optional[Balance]:
        if not date:
            date = datetime.now(tz=pytz.UTC)
        if force or (
                date - self._last_fetch > timedelta(seconds=PRIORITY_INTERVALS[priority]) and not self.client.rekt_on):
            self._last_fetch = date
            try:
                balance = await self._get_balance(date, upnl=upnl)
            except ResponseError as e:
                return db_balance.Balance(
                    time=date,
                    error=e.human
                )
            if not balance.time:
                balance.time = date
            balance.client_id = self.client_id
            balance.total_transfered = getattr(
                self.client.currently_realized, 'total_transfered', Decimal(0)
            )
            # TODO
            # await self.client.update_journals(balance, date.date(), self.db)
            return balance
        elif self.client.rekt_on:
            return db_balance.Balance(amount=0.0, error=None, time=date)
        else:
            return None

    async def get_executions(self,
                             since: datetime) -> tuple[List[Transfer], List[Execution], List[MiscIncome]]:
        # transfers, (execs, misc) = await asyncio.gather(
        #    self._get_transfers(since),
        #    # TODO: change init param
        #    self._get_executions(since, init=self.client.last_execution_sync is None)
        # )
        transfers = await self.get_transfers(since)
        execs, misc = await self._get_executions(since, init=self.client.last_execution_sync is None)
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
        return transfers, execs, misc

    async def intelligent_get_balance(self,
                                      keep_errors=False,
                                      date: datetime = None) -> Optional["Balance"]:
        """
        Fetch the clients balance, only saving if it makes sense to do so.
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
        async with self.db_maker() as db:
            client: Client = await db.get(
                Client,
                self.client_id,
                options=(selectinload(Client.recent_history),)  # Needs to be an iterable
            )
            self.client = client
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
                return result

    async def get_transfers(self, since: datetime = None) -> List[Transfer]:
        if not since:
            since = (
                    self.client.last_transfer_sync or datetime.now(pytz.utc) - timedelta(days=180)
            )
        raw_transfers = await self._get_transfers(since)
        if raw_transfers:
            raw_transfers.sort(key=lambda transfer: transfer.time)
            return [
                Transfer(
                    amount=await self._convert_to_usd(raw_transfer.amount, raw_transfer.coin, raw_transfer.time),
                    time=raw_transfer.time,
                    extra_currencies=(
                        {raw_transfer.coin: raw_transfer.amount}
                        if not self._usd_like(raw_transfer.coin) else None
                    ),
                    coin=raw_transfer.coin,
                    client_id=self.client_id
                )
                for raw_transfer in raw_transfers
            ]
        else:
            return []

    async def synchronize_positions(self):
        """
        Responsible for synchronizing the client with the exchange.
        Fetches executions, transfers and additional incomes (kickback fees, etc.)
        """
        async with self.db_maker() as db:

            client: Client = await db.get(Client, self.client_id, options=(selectinload(Client.trades),))
            self.client = client

            since = client.last_execution_sync

            async with self.db_lock:
                check_executions = await db_all(
                    select(Execution).order_by(
                        asc(Execution.time)
                    ).join(
                        Execution.trade
                    ).filter(
                        Trade.client_id == self.client_id,
                        Execution.time > since if since else True
                    ),
                    session=db
                )

            transfers, all_executions, misc = await self.get_executions(since)
            executions_by_symbol = utils.groupby(all_executions, lambda e: e.symbol)

            valid_until = since
            execution_qty = check_qty = Decimal(0)
            for execution, check in itertools.zip_longest(check_executions, all_executions):
                if execution:
                    execution_qty += execution.qty
                if check:
                    check_qty += check.qty
                if execution_qty == check_qty:
                    valid_until = execution.time if execution else check.time

            all_executions = [e for e in all_executions if e.time > valid_until] if valid_until else all_executions

            async with self.db_lock:
                for trade in self.client.trades:
                    await trade.reverse_to(valid_until, db_session=db)

                await db.flush()

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
                        current_executions = [to_exec]
                        # TODO: What if the start point isnt from 0 ?
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
                        if len(current_executions) > 1:
                            to = current_executions[-1].time
                        else:
                            to = datetime.now(pytz.utc)
                        try:
                            ohlc_data = await self._get_ohlc(
                                symbol,
                                since=current_executions[0].time,
                                to=to
                            )
                        except ResponseError:
                            ohlc_data = []
                        current_trade = None
                        for item in combine_time_series(ohlc_data, current_executions):
                            if isinstance(item, Execution):
                                current_trade = await self._add_executions_db(db, [item], realtime=False)
                            elif isinstance(item, OHLC) and current_trade:
                                current_trade.update_pnl(
                                    current_trade.calc_upnl(item.open),
                                    realtime=False,
                                    now=item.time
                                )
                        await db.flush()
                        to_exec = next(exec_iter, None)

            await self._update_realized_balance(db)

            current_balance = self.client.currently_realized

            async with self.db_lock:
                pnl_data = await db_all(
                    select(PnlData).filter(
                        PnlData.trade_id.in_(set(execution.trade_id for execution in all_executions))
                    ).order_by(
                        desc(PnlData.time)
                    ),
                    session=db
                )
                pnl_iter = iter(pnl_data)
                cur_pnl = next(pnl_iter, None)

                # Start Balance:
                # 11.4. 100
                # Executions
                # 10.4. +10
                # 8.4.  -20
                # 7.4.  NONE <- required because otherwise the last ones won't be accurate
                # PnlData
                # 9.4. 5U
                # New Balances
                # 10.4. 100
                # 8.4. 90
                # 7.4. 110

                transfer_iter = iter(
                    zip(
                        reversed(transfers),
                        reversed(
                            list(itertools.accumulate((t.amount for t in transfers),
                                                      initial=current_balance.total_transfered or 0))
                        )
                    )
                )

                misc_iter = iter(reversed(misc))

                current_transfer, current_transferred = next(transfer_iter, (None, None))
                if current_transferred:
                    current_balance.total_transfered = current_transferred

                current_misc = next(misc_iter, None)
                balances = []

                for prev_exec, execution, next_exec in utils.prev_now_next(reversed(all_executions),
                                                                           skip=lambda e: e.type == ExecType.TRANSFER):
                    new_balance = db_balance.Balance(
                        realized=current_balance.realized,
                        unrealized=current_balance.unrealized,
                        total_transfered=current_transferred,
                        time=execution.time,
                        client=self.client
                    )
                    pnl_by_trade = {}

                    while current_transfer and execution.time <= current_transfer.time:
                        new_balance.realized -= current_transfer.amount
                        current_transfer, current_transferred = next(transfer_iter, (None, None))
                    new_balance.total_transfered = current_transferred

                    while current_misc and execution.time <= current_misc.time:
                        new_balance.realized -= current_misc.amount
                        current_misc = next(misc_iter, None)

                    if next_exec:
                        while cur_pnl and cur_pnl.time > next_exec.time:
                            if cur_pnl.time < execution.time and cur_pnl.trade_id not in pnl_by_trade:
                                pnl_by_trade[cur_pnl.trade_id] = cur_pnl
                            cur_pnl = next(pnl_iter, None)
                    if prev_exec:
                        if prev_exec.type == ExecType.TRADE:
                            if prev_exec.realized_pnl:
                                new_balance.realized -= prev_exec.realized_pnl
                            if prev_exec.commission:
                                new_balance.realized += prev_exec.commission

                            new_balance.unrealized = new_balance.realized + sum(
                                pnl_data.unrealized
                                if
                                tr_id != execution.trade_id
                                else
                                pnl_data.unrealized - (execution.realized_pnl or 0)
                                for tr_id, pnl_data in pnl_by_trade.items()
                            )

                    if execution.trade:
                        if execution.id == execution.trade.initial_execution_id:
                            execution.trade.init_balance = new_balance
                    else:
                        pass

                    if not next_exec or next_exec.time != execution.time:
                        balances.append(new_balance)
                    current_balance = new_balance

                if all_executions:
                    first_execution = all_executions[0]
                    balances.append(
                        db_balance.Balance(
                            realized=current_balance.realized + (first_execution.commission or 0),
                            unrealized=current_balance.unrealized + (first_execution.commission or 0),
                            total_transfered=current_balance.total_transfered,
                            time=first_execution.time - timedelta(seconds=1),
                            client=self.client
                        )
                    )

                db.add_all(balances)

                await self._add_transfers(transfers, db)

            client.last_execution_sync = client.last_transfer_sync = utils.utc_now()
            await db.commit()

            if all_executions:
                await self.client.as_redis().set_last_exec(all_executions[-1].time)
                #new = await db
                await self.pub_trade(Category.NEW, all_executions[-1].trade)

    async def _add_transfers(self, transfers: list[Transfer], db: AsyncSession):
        if transfers:
            to_update: list['Balance'] = await db_all(
                self.client.history.statement.filter(
                    db_balance.Balance.time > transfers[0].time
                ),
                session=db
            )

            # to_update | transfers
            # 1.1. 100  |
            #           | 2.1. -100
            # 3.1. 300  |
            #           | 4.1.  200
            # 5.1. 500  |
            # ---------------------
            # After Update:
            # 1.1 100
            # 3.1. 200 (300 - 100)
            # 5.1. 600 (500 - 100 + 200 = 500 + 100)

            transfer_iter = iter(transfers)
            next_transfer = next(transfer_iter, None)
            cur_offset = 0
            for update in to_update:
                while next_transfer and update.time > next_transfer.time:
                    cur_offset += next_transfer.amount
                    next_transfer = next(transfer_iter, None)
                update.total_transfered += cur_offset
            db.add_all(transfers)

    async def get_client(self, db: AsyncSession) -> Client:
        client = await db.get(Client, self.client_id)
        if client is None:
            await self.messenger.pub_channel(NameSpace.CLIENT, Category.DELETE, obj={'id': self.client_id})
            raise ClientDeletedError()
        return client

    async def _update_realized_balance(self, db: AsyncSession):
        balance = await self.get_balance(
            Priority.FORCE,
            datetime.now(pytz.utc),
            upnl=False
        )
        if balance:
            client = await self.get_client(db)
            client.currently_realized = balance
            db.add(balance)
            await db.flush()
            return balance

    async def _on_execution(self, execution: Execution):
        self._pending_execs.append(execution)
        if self._waiter and not self._waiter.done():
            self._waiter.cancel()
        asyncio.create_task(self._exec_waiter())

    async def _exec_waiter(self):
        """
        Task used for grouping executions which happen close together (common with market orders)
        in order to reduce load (less transactions to the database)
        """
        self._waiter = asyncio.create_task(
            asyncio.sleep(self._execution_dedupe_delay)
        )
        await self._waiter
        execs = []
        while self._pending_execs:
            execs.append(self._pending_execs.popleft())
        await self._add_executions(execs)

    async def _add_executions(self, executions: list[Execution], realtime=True):
        async with self.db_maker() as db:
            return await self._add_executions_db(db, executions, realtime)

    async def _add_executions_db(self, db: AsyncSession, executions: list[Execution], realtime=True) -> Trade:
        publish = []
        if executions:
            if realtime:
                # Updating LAST_EXEC is siginificant for caching
                asyncio.create_task(
                    self.client.as_redis().set_last_exec(executions[-1].time)
                )
                await self._update_realized_balance(db)

            for execution in executions:

                execution.time = execution.time.replace(microsecond=0)

                active_trade: Trade = await db_unique(
                    select(Trade).filter(
                        Trade.symbol == execution.symbol,
                        Trade.client_id == self.client_id,
                        Trade.open_qty > 0.0
                    ),
                    Trade.initial,
                    Trade.max_pnl,
                    Trade.min_pnl,
                    session=db
                )

                self.in_position = True

                if active_trade:
                    # Update existing trade
                    execution.trade_id = active_trade.id
                    db.add(execution)

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
                                time=execution.time,
                                type=execution.type
                            )
                            # Because the execution is "split" we also have to assign
                            # the commissions accordingly
                            new_execution.commission = execution.commission * new_execution.qty / execution.qty
                            execution.commission -= new_execution.commission
                            execution.qty = active_trade.open_qty

                            new_trade = trade_from_execution(new_execution)
                            new_trade.client_id = self.client_id

                            db.add(new_trade)
                            publish.append((Category.NEW, new_trade))
                        if execution.qty <= active_trade.open_qty:
                            if active_trade.exit is None:
                                active_trade.exit = execution.price
                            else:
                                active_trade.exit = weighted_avg((active_trade.exit, execution.price),
                                                                 (active_trade.qty - active_trade.open_qty,
                                                                  execution.qty))

                            active_trade.open_qty -= execution.qty
                            rpnl = active_trade.calc_rpnl()
                            # Only set realized pnl if it isn't given by exchange implementation
                            if execution.realized_pnl is None:
                                execution.realized_pnl = rpnl - (active_trade.realized_pnl or Decimal(0))
                            active_trade.realized_pnl = rpnl
                            if execution.commission:
                                active_trade.total_commissions += execution.commission

                            if active_trade.open_qty.is_zero():
                                if self and not new_execution:
                                    self.in_position = False
                                active_trade.update_pnl(0, now=execution.time)
                                publish.append((Category.FINISHED, active_trade))

                    publish.append((Category.UPDATE, active_trade))
                else:
                    active_trade = trade_from_execution(execution)
                    if realtime:
                        client = await self.get_client(db)
                        active_trade.init_balance = client.currently_realized
                    active_trade.client_id = self.client_id

                    db.add(active_trade)
                    publish.append((Category.NEW, active_trade))

                await db.flush()

            if realtime:
                await db.commit()
                for args in publish:
                    self.pub_trade(*args)
            return active_trade

    def pub_trade(self, category: Category, trade: Trade):
        return self.messenger.pub_channel(NameSpace.TRADE, category, trade.serialize(), trade.id)

    async def _convert_to_usd(self, amount: Decimal, coin: str, date: datetime):
        if self._usd_like(coin):
            return amount

    async def _get_ohlc(self, market: str, since: datetime, to: datetime, resolution_s: int = None,
                        limit: int = None) -> List[OHLC]:
        pass

    async def _get_executions(self,
                              since: datetime,
                              init=False) -> tuple[List[Execution], List[MiscIncome]]:
        return [], []

    @classmethod
    def _calc_resolution(cls,
                         n: int,
                         resolutions_s: List[int],
                         since: datetime,
                         to: datetime = None) -> Optional[Tuple[int, int]]:
        """
        Small helper for finding out which resolution [s] suits a given amount of data points requested best.

        Used in order to avoid unreasonable amounts (or too little in general)
        of data being fetched, look which timeframe suits the given limit best

        :param n: n data points
        :param resolutions_s: Possibilities (have to be sorted!)
        :param since: used to calculate seconds passed
        :param now: [optional] can be passed to replace datetime.now()
        :return: Fitting resolution or None
        """
        # In order to avoid unreasonable amounts (or too little in general)
        # of data being fetched, look which timeframe suits the given limit best
        to = to or datetime.now(pytz.utc)
        for res in resolutions_s:
            current_n = (to - since).total_seconds() // res
            if current_n <= n:
                return int(current_n), res
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

    async def cleanup(self):
        pass

    async def startup(self):
        # self.client = await db_select(
        #    Client,
        #    eager=[Client.trades], session=self.db,
        #    id=self.client_id
        # )
        await self._connect()

    async def _connect(self):
        pass

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> List[RawTransfer]:
        logger.warning(f'Exchange {self.exchange} does not implement get_transfers')
        return []

    @abc.abstractmethod
    async def _get_balance(self, time: datetime, upnl=True):
        logger.error(f'Exchange {self.exchange} does not implement _get_balance')
        raise NotImplementedError(f'Exchange {self.exchange} does not implement _get_balance')

    @abc.abstractmethod
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        logger.error(f'Exchange {self.exchange} does not implement _sign_request')

    def _set_rate_limit_parameters(self, response: ClientResponse):
        pass

    @classmethod
    def _check_for_error(cls, response_json: Dict, response: ClientResponse):
        pass

    @classmethod
    async def _process_response(cls, response: ClientResponse) -> dict:
        response_json = await response.json(loads=customjson.loads)
        try:
            response.raise_for_status()
        except ClientResponseError as e:
            logger.error(f'{e}\n{response_json=}\n{response.reason=}')

            error = ''
            if response.status == 400:
                error = "400 Bad Request. This is probably an internal bug, please contact dev"
            elif response.status == 401:
                error = f"401 Unauthorized ({response.reason}). You might want to check your API access"
            elif response.status == 403:
                error = f"403 Access Denied ({response.reason}). You might want to check your API access"
            elif response.status == 404:
                error = f"404 Not Found. This is probably an internal bug, please contact dev"
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
            if cls._response_result and cls._response_result in response_json:
                return response_json[cls._response_result]
            return response_json

    @classmethod
    def set_weights(cls, weight: int, response: ClientResponse):
        for limit in cls._limits:
            limit.amount -= weight or limit.default_weight

    @classmethod
    async def _request_handler(cls):
        """
        Task which is responsible for putting out the requests
        for this specific Exchange.

        All requests have to be put onto the :cls._request_queue:
        so that the handler can properly execute them according to the current
        rate limit states. If there is enough weight available it will also
        decide to run requests in parallel.
        """
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

                async with cls._http.request(request.method,
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
                    except InvalidClientError as e:
                        logger.error(f'Error while executing request: {e.human} {e.root_error}')
                        item.future.set_exception(e)
                    except ResponseError as e:
                        if e.root_error.status == 401:
                            e = InvalidClientError(root_error=e.root_error, human=e.human)
                        logger.error(f'Error while executing request: {e.human} {e.root_error}')
                        item.future.set_exception(e)
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
        url = (endpoint or (self._SANDBOX_ENDPOINT if self.client.sandbox else self._ENDPOINT)) + path
        request = Request(
            method,
            url,
            path,
            headers or {},
            params or {},
            data,
            source=self.client
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
        try:
            return await future
        except InvalidClientError:
            if self.client_id:
                async with self.db_maker() as db:
                    await db.execute(
                        update(Client).where(Client.id == self.client_id).values(invalid=True)
                    )
                await self.disconnect()
                self.messenger.pub_channel(NameSpace.CLIENT, Category.UPDATE, {
                    'id': self.client_id, 'invalid': True
                })
            raise

    def _get(self, path: str, **kwargs):
        return self._request('GET', path, **kwargs)

    def _post(self, path: str, **kwargs):
        return self._request('POST', path, **kwargs)

    def _put(self, path: str, **kwargs):
        return self._request('PUT', path, **kwargs)

    def _symbol(self, coin: str):
        return f'{coin}/{self.client.currency or "USD"}'

    @classmethod
    def _usd_like(cls, coin: str):
        return coin in ('USD', 'USDT', 'USDC', 'BUSD', 'USTC', 'UST')

    @classmethod
    def _query_string(cls, params: Dict):
        query_string = urllib.parse.urlencode(params)
        return f"?{query_string}" if query_string else ""

    @classmethod
    def _parse_ts(cls, ts: Union[int, float]):
        return datetime.fromtimestamp(ts, pytz.utc)

    @classmethod
    def _date_as_ms(cls, datetime: datetime):
        return int(datetime.timestamp() * 1000)

    @classmethod
    def _date_as_s(cls, datetime: datetime):
        return int(datetime.timestamp())

    @classmethod
    def _parse_ms(cls, ts_ms: int | float):
        return datetime.fromtimestamp(ts_ms / 1000, pytz.utc)

    def __repr__(self):
        return f'<Worker exchange={self.exchange} client_id={self.client_id}>'
