from __future__ import annotations

import abc
import asyncio
import itertools
import logging
import time
import urllib.parse
from asyncio import Future, Task
from asyncio.queues import PriorityQueue
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import List, Dict, Tuple, Optional, Union, Set
from typing import NamedTuple
from typing import TYPE_CHECKING

import aiohttp.client
import pytz
from aiohttp import ClientResponse, ClientResponseError
from sqlalchemy import select, desc, asc, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, sessionmaker, joinedload

import core
from core import json as customjson
from database.dbasync import db_unique, db_all, db_select
from database.dbmodels.client import Client, ClientState
from database.dbmodels.execution import Execution
from database.dbmodels.pnldata import PnlData
from database.dbmodels.trade import Trade
from database.dbmodels.transfer import Transfer, RawTransfer
from database.enums import Priority, ExecType, Side
from database.errors import RateLimitExceeded, ExchangeUnavailable, ExchangeMaintenance, ResponseError, \
    InvalidClientError, ClientDeletedError
from common.messenger import TableNames, Category, Messenger
from database.models.miscincome import MiscIncome
from database.models.ohlc import OHLC
from database.models.market import Market
from core.utils import combine_time_series

if TYPE_CHECKING:
    from database.dbmodels.balance import Balance

import database.dbmodels.balance as db_balance

logger = logging.getLogger(__name__)


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


PRIORITY_INTERVALS = {
    Priority.LOW: 60,
    Priority.MEDIUM: 30,
    Priority.HIGH: 15,
    Priority.FORCE: 1
}


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
                 execution_dedupe_seconds: float = 5e-3, ):

        self.client_id = client.id
        self.exchange = client.exchange
        self.messenger = messenger
        self.client: Optional[Client] = client
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
        if force or date - self._last_fetch > timedelta(seconds=PRIORITY_INTERVALS[priority]):
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
            return balance
        else:
            return None

    async def get_executions(self,
                             since: datetime) -> tuple[List[Transfer], List[Execution], List[MiscIncome]]:
        transfers = await self.get_transfers(since)
        execs, misc = await self._get_executions(since, init=self.client.last_execution_sync is None)
        # for transfer in transfers:
        #     if transfer.coin:
        #         raw_amount = transfer.extra_currencies.get(transfer.coin, transfer.amount)
        #         transfer.execution = Execution(
        #             symbol=self._symbol(transfer.coin),
        #             qty=abs(raw_amount),
        #             price=transfer.amount / raw_amount,
        #             side=Side.BUY if transfer.amount > 0 else Side.SELL,
        #             time=transfer.time,
        #             type=ExecType.TRANSFER,
        #             commission=transfer.commission
        #         )
        #         execs.append(transfer.execution)
        for transfer in transfers:
            if transfer.execution:
                execs.append(transfer.execution)
        execs.sort(key=lambda e: e.time)
        return transfers, execs, misc

    async def intelligent_get_balance(self,
                                      date: datetime = None) -> Optional["Balance"]:
        """
        Fetch the clients balance, only saving if it makes sense to do so.
        database session to ues
        :param date:
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

                if result:
                    history = client.recent_history
                    if len(history) > 2:
                        # If balance hasn't changed at all, why bother keeping it?
                        if result == history[-1] == history[-2]:
                            history[-1].time = date
                            return None
                    if result.error:
                        logger.error(f'Error while fetching {client.id=} balance: {result.error}')
                    else:
                        await client.as_redis().set_balance(result)
            else:
                raise InvalidClientError
            return result

    async def get_transfers(self, since: datetime = None) -> List[Transfer]:
        if not since:
            since = self.client.last_transfer_sync
        raw_transfers = await self._get_transfers(since)
        if raw_transfers:
            raw_transfers.sort(key=lambda transfer: transfer.time)

            result = []
            for raw_transfer in raw_transfers:
                amount = await self._convert_to_usd(raw_transfer.amount, raw_transfer.coin, raw_transfer.time)
                if amount:
                    transfer = Transfer(
                        client_id=self.client_id
                    )

                    transfer.execution = Execution(
                        symbol=self._symbol(raw_transfer.coin),
                        qty=abs(raw_transfer.amount),
                        price=raw_transfer.amount / amount,
                        side=Side.BUY if raw_transfer.amount > 0 else Side.SELL,
                        time=raw_transfer.time,
                        type=ExecType.TRANSFER,
                        commission=None
                    )
                    result.append(transfer)
            return result
        else:
            return []

    async def synchronize_positions(self):
        """
        Responsible for synchronizing the client with the exchange.
        Fetches executions, transfers and additional incomes (kickback fees, etc.)

        The flow can be summarized the following way:
        - Fetch all executions and transfers that happend since last sync and all executions
        - Check the fetched ones against executions that are already in the system
        - Delete trades if they are invalid (could happen due to websocket connection loss etc.)
        - Generate balances based on valid executions
        - Generate trades including pnl data
        - Set the unrealized field of each balance
          (can't be done in advance because it depends on pnl data but creating pnl data depends on balances)
        """
        async with self.db_maker() as db:
            client: Client = await db_select(
                Client, Client.id == self.client_id,
                eager=[
                    (Client.trades, Trade.executions),
                    Client.currently_realized
                ],
                session=db
            )
            client.state = ClientState.SYNCHRONIZING
            await db.commit()
            self.client = client

            since = client.last_execution_sync

            transfers, all_executions, misc = await self.get_executions(since)

            check_executions = await db_all(
                select(Execution).order_by(
                    asc(Execution.time)
                ).join(Execution.trade).where(
                    Trade.client_id == self.client_id,
                    Execution.time > since if since else True
                ),
                session=db
            )

            valid_until = since
            exec_sum = check_sum = Decimal(0)
            for execution, check in itertools.zip_longest(all_executions, check_executions):
                if execution:
                    exec_sum += abs(execution.qty or execution.realized_pnl)
                if check:
                    check_sum += abs(check.qty or check.realized_pnl)
                if exec_sum == check_sum and exec_sum != 0:
                    valid_until = execution.time if execution else check.time

            all_executions = [e for e in all_executions if e.time > valid_until] if valid_until else all_executions

            executions_by_symbol = core.groupby(all_executions, lambda e: e.symbol)

            for trade in self.client.trades:
                if valid_until:
                    await trade.reverse_to(valid_until, db=db)
                else:
                    await db.delete(trade)

            if client.currently_realized and valid_until and valid_until < client.currently_realized.time:
                await db.execute(
                    delete(db_balance.Balance).where(
                        db_balance.Balance.client_id == client.id,
                        db_balance.Balance.time > valid_until
                    )
                )

            await db.flush()

            def get_time(b: Balance):
                return b.time

            current_balance = await self._update_realized_balance(db)

            if executions_by_symbol:
                for symbol, executions in executions_by_symbol.items():
                    if not symbol:
                        return

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
                                if to_exec.type == ExecType.TRADE:
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
                                current_trade = await self._add_executions(db,
                                                                           [item],
                                                                           realtime=False)
                            elif isinstance(item, OHLC) and current_trade:
                                current_trade.update_pnl(
                                    current_trade.calc_upnl(item.open),
                                    now=item.time,
                                )
                        to_exec = next(exec_iter, None)

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

            misc_iter = reversed(misc)
            current_misc = next(misc_iter, None)

            balances = []

            pnl_data = await db_all(
                select(PnlData).filter(
                    PnlData.trade_id.in_(execution.trade_id for execution in all_executions)
                ).order_by(
                    desc(PnlData.time)
                ),
                session=db
            )

            pnl_iter = iter(pnl_data)
            cur_pnl = next(pnl_iter, None)

            # Note that we iterate through the executions reversed because we have to reconstruct
            # the history from the only known point (which is the present)
            for prev_exec, execution, next_exec in core.prev_now_next(reversed(all_executions)):
                execution: Execution
                prev_exec: Execution
                next_exec: Execution

                new_balance = db_balance.Balance(
                    realized=current_balance.realized,
                    unrealized=current_balance.unrealized,
                    time=execution.time,
                    client=self.client
                )
                new_balance.__realtime__ = False

                if execution.type == ExecType.TRANSFER:
                    new_balance.realized -= execution.size

                while current_misc and execution.time <= current_misc.time:
                    new_balance.realized -= current_misc.amount
                    current_misc = next(misc_iter, None)

                pnl_by_trade = {}

                if next_exec:
                    # The closest pnl from each trade should be taken into account
                    while cur_pnl and cur_pnl.time > next_exec.time:
                        if cur_pnl.time < execution.time and cur_pnl.trade_id not in pnl_by_trade:
                            pnl_by_trade[cur_pnl.trade_id] = cur_pnl
                        cur_pnl = next(pnl_iter, None)

                if prev_exec:
                    if prev_exec.realized_pnl:
                        new_balance.realized -= prev_exec.realized_pnl
                    if prev_exec.commission:
                        new_balance.realized += prev_exec.commission

                    current_balance.unrealized = current_balance.realized + sum(
                        # Note that when upnl of the current execution is included the rpnl that was realized
                        # can't be included anymore
                        pnl_data.unrealized
                        if tr_id != execution.trade_id
                        else pnl_data.unrealized - (execution.realized_pnl or 0)
                        for tr_id, pnl_data in pnl_by_trade.items()
                    )

                if execution.trade and execution.trade.initial_execution_id == execution.id:
                    execution.trade.init_balance = new_balance

                # Don't bother adding multiple balances for executions happening as a direct series of events
                if not prev_exec or prev_exec.time != execution.time:
                    balances.append(new_balance)
                current_balance = new_balance

            if all_executions:
                first_execution = all_executions[0]
                balances.append(
                    db_balance.Balance(
                        realized=current_balance.realized + (first_execution.commission or 0),
                        unrealized=current_balance.unrealized + (first_execution.commission or 0),
                        time=first_execution.time - timedelta(seconds=1),
                        client=self.client
                    )
                )

            db.add_all(balances)
            db.add_all(transfers)
            await db.flush()

            client.last_execution_sync = client.last_transfer_sync = core.utc_now()
            client.state = ClientState.OK

            await db.commit()

            if all_executions:
                await self.client.as_redis().set_last_exec(all_executions[-1].time)

    async def get_client(self, db: AsyncSession) -> Client:
        client = await db.get(Client, self.client_id)
        if client is None:
            await self.messenger.pub_channel(TableNames.CLIENT, Category.DELETE, obj={'id': self.client_id})
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
        async with self.db_maker() as db:
            try:
                trade = await self._add_executions(db, execs, realtime=True)
            except Exception as e:
                self._logger.error('Error while adding executions')
            await db.commit()
            self._logger.debug(f'Added executions {execs} {trade}')

    async def _add_executions(self,
                              db: AsyncSession,
                              executions: list[Execution],
                              realtime=True,
                              current_balance: Balance = None):
        if not current_balance:
            client = await self.get_client(db)
            current_balance = client.currently_realized

        if executions:
            active_trade: Optional[Trade] = None
            if realtime:
                # Updating LAST_EXEC is siginificant for caching
                asyncio.create_task(
                    self.client.as_redis().set_last_exec(executions[-1].time)
                )
                await self._update_realized_balance(db)

            for execution in executions:

                async def get_trade(symbol: str):

                    stmt = select(Trade).where(
                        #Trade.symbol.like(f'{symbol}%'),
                        Trade.symbol == symbol,
                        Trade.symbol == execution.symbol,
                        Trade.client_id == self.client_id
                    )

                    # The distinguishing here is pretty important because Liquidation Execs can happen
                    # after a trade has been closed on paper (e.g. insurance fund on binance). These still have to be
                    # attributed to the corresponding trade.
                    if execution.type in (ExecType.TRADE, ExecType.TRANSFER):
                        stmt = stmt.where(
                            Trade.is_open
                        )
                    elif execution.type in (ExecType.FUNDING, ExecType.LIQUIDATION):
                        stmt = stmt.order_by(
                            desc(Trade.open_time)
                        )
                    return await db_unique(stmt,
                                           Trade.executions,
                                           Trade.init_balance,
                                           Trade.initial,
                                           Trade.max_pnl,
                                           Trade.min_pnl,
                                           session=db)

                if self._exclude_from_trade(execution):
                    continue

                active_trade = await get_trade(execution.symbol)

                if active_trade:
                    # Update existing trade

                    execution.__realtime__ = realtime
                    db.add(execution)

                    active_trade.__realtime__ = realtime
                    new_trade = active_trade.add_execution(execution, current_balance)
                    if new_trade:
                        db.add(new_trade)
                        new_trade.__realtime__ = realtime
                        active_trade = new_trade
                else:
                    active_trade = Trade.from_execution(execution, self.client_id, current_balance)
                    active_trade.__realtime__ = realtime
                    db.add(active_trade)
            return active_trade

    async def _convert(self, amount: Decimal, to: str, from_ccy: str, date: datetime):
        pass

    async def _convert_to_usd(self, amount: Decimal, coin: str, date: datetime):
        if self._usd_like(coin):
            return amount
        # return await self._convert()

    async def _get_ohlc(self, market: str, since: datetime, to: datetime, resolution_s: int = None,
                        limit: int = None) -> List[OHLC]:
        raise NotImplementedError

    async def _get_executions(self,
                              since: datetime,
                              init=False) -> tuple[List[Execution], List[MiscIncome]]:
        raise NotImplementedError

    @classmethod
    def _exclude_from_trade(cls, execution: Execution):
        return False

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
        :return: Fitting resolution or  None
        """
        to = to or datetime.now(pytz.utc)
        for res in resolutions_s:
            current_n = (to - since).total_seconds() // res
            if current_n <= n:
                return int(current_n), res
        return None

    async def cleanup(self):
        pass

    async def startup(self):
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
    def get_market(cls, raw: str) -> Market:
        raise NotImplementedError

    @classmethod
    def get_symbol(cls, market: Market) -> str:
        return market.base + market.quote

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
        so that the handler can properly Knockkek ist geil execute them according to the current
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

                try:
                    async with cls._http.request(request.method,
                                                 request.url,
                                                 params=request.params,
                                                 headers=request.headers,
                                                 json=request.json) as resp:
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
            except Exception as e:
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
                        update(Client).where(Client.id == self.client_id).values(state=ClientState.INVALID)
                    )
            raise

    def get(self, path: str, **kwargs):
        return self._request('GET', path, **kwargs)

    def post(self, path: str, **kwargs):
        return self._request('POST', path, **kwargs)

    def put(self, path: str, **kwargs):
        return self._request('PUT', path, **kwargs)

    def _symbol(self, coin: str):
        return f'{coin}/{self.client.currency or "USD"}'

    @classmethod
    def _usd_like(cls, coin: str):
        return coin in ('USD', 'USDT', 'USDC', 'BUSD')

    @classmethod
    def _query_string(cls, params: Dict):
        query_string = urllib.parse.urlencode(params)
        return f"?{query_string}" if query_string else ""

    @classmethod
    def parse_ts(cls, ts: Union[int, float]):
        return datetime.fromtimestamp(ts, pytz.utc)

    @classmethod
    def date_as_ms(cls, datetime: datetime):
        return int(datetime.timestamp() * 1000)

    @classmethod
    def date_as_s(cls, datetime: datetime):
        return int(datetime.timestamp())

    @classmethod
    def parse_ms(cls, ts_ms: int | float):
        return datetime.fromtimestamp(ts_ms / 1000, pytz.utc)

    def __repr__(self):
        return f'<Worker exchange={self.exchange} client_id={self.client_id}>'
