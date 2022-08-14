from __future__ import annotations
import abc
import asyncio
import logging
import time
import urllib.parse
import math
from asyncio import Future, Task
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Callable, Dict, Tuple, Optional, Union, Set
import aiohttp.client
import pytz
from aiohttp import ClientResponse, ClientResponseError
from typing import NamedTuple
from asyncio.queues import PriorityQueue

from sqlalchemy import select, desc
from sqlalchemy.orm import joinedload

import tradealpha.common.utils as utils
from tradealpha.common.dbasync import async_session, db_unique, db_all, db_first
from tradealpha.common.dbmodels.execution import Execution
from tradealpha.common.dbmodels.trade import Trade, trade_from_execution

import tradealpha.common.dbmodels.balance as db_balance
from tradealpha.common.dbmodels.transfer import Transfer, RawTransfer
from tradealpha.common.config import PRIORITY_INTERVALS
from tradealpha.common.enums import Priority
from tradealpha.common.errors import RateLimitExceeded, ExchangeUnavailable, ExchangeMaintenance, ResponseError
from tradealpha.common.messenger import NameSpace, Category, Messenger

from tradealpha.common.dbmodels.client import Client
from typing import TYPE_CHECKING

from tradealpha.common.exchanges.exchangeworker import ExchangeWorker

if TYPE_CHECKING:
    from tradealpha.common.dbmodels.balance import Balance


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
        return self.priority.value > other.priority.values

    def __lt__(self, other):
        return self.priority.value < other.priority.values


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


class ExchangeManager:

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
    _max_weight = 60
    _weight_available = _max_weight
    _default_weight = 1
    _last_request_ts = None

    def __init__(self,
                 client: Client,
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

        self._session = session
        self._request_task = asyncio.create_task(self._request_handler())
        self._request_queue = PriorityQueue()

    async def get_balance(self,
                          priority: Priority = Priority.MEDIUM,
                          time: datetime = None,
                          force=False,
                          upnl=True) -> Optional[db_balance.Balance]:
        if not time:
            time = datetime.now(tz=pytz.UTC)
        if force or (time - self._last_fetch > timedelta(seconds=PRIORITY_INTERVALS[priority]) and not self.client.rekt_on):
            self._last_fetch = time
            try:
                balance = await self._get_balance(time, upnl=upnl)
            except ResponseError as e:
                return db_balance.Balance(
                    amount=0,
                    time=time,
                    error=e.human
                )
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

    async def intelligent_get_balance(self, keep_errors=False, commit=True) -> Optional["Balance"]:
        """
        Fetch the clients balance, only saving if it makes sense to do so.
        :param keep_errors:
        whether to return the balance if it resulted in an error
        :param commit:
        whether to not commit the new balance. Can be used if calling this function
        multiple times.
        NOTE: after calling all you should also publish the balances accordingly
        :return:
        new balance object
        """
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
                if (
                    latest_balance.unrealized == result.unrealized
                    and
                    history[history_len - 2].unrealized, result.unrealized
                ):
                    latest_balance.time = time
            if result.error:
                logger.error(f'Error while fetching {client.id=} balance: {result.error}')
                if keep_errors:
                    return result
            else:
                async_session.add(result)
                if result.amount <= self.rekt_threshold and not client.rekt_on:
                    client.rekt_on = time
                    self.messenger.pub_channel(NameSpace.CLIENT, Category.REKT, channel_id=client.id,
                                               obj={'id': client.id})
            if commit:
                await async_session.commit()
                self.messenger.pub_channel(NameSpace.BALANCE, Category.NEW, channel_id=client.id,
                                           obj=result.id)
            return result

    async def update_transfers(self):
        """

        :param since:
        :return:
        """
        raw_transfers = await self._get_transfers(
            self.client.currently_realized.time if self.client.currently_realized and False
            else datetime.now(pytz.utc) - timedelta(days=180)
        )
        if raw_transfers:
            raw_transfers.sort(key=lambda transfer: transfer.time)
            transfers = [
                Transfer(
                    amount=await self._convert_to_usd(raw_transfer.amount, raw_transfer.coin, raw_transfer.time),
                    time=raw_transfer.time,
                    extra_currencies={raw_transfer.coin: raw_transfer.amount}
                    if raw_transfer.coin != "USD" and raw_transfer.coin != "USDT" else None,
                    client_id=self.client_id
                )
                for raw_transfer in raw_transfers
            ]
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

        await self._update_realized_balance()

    async def _convert_to_usd(self, amount: float, coin: str, date: datetime):
        if coin == "USD" or coin == "USDT":
            return amount

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

    async def _update_realized_balance(self):
        self._waiter = asyncio.sleep(self._execution_dedupe_delay)
        await self._waiter
        await self.update_transfers()
        balance = await self.get_balance(Priority.FORCE, datetime.now(pytz.utc), upnl=False)
        if balance:
            #balance = await self.intelligent_get_balance(self.client, priority=Priority.FORCE)
            #balance = await um.UserManager().get_client_balance(self.client, priority=Priority.FORCE)
            self.client.currently_realized = balance
            await async_session.commit()

    async def _on_execution(self, execution: Execution, realtime=True):

        if realtime and not self._waiter.done():
            self._waiter.cancel()

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
                        if self and not new_execution:
                            self.in_position = False
                    else:
                        active_trade.open_qty -= execution.qty
                    rpnl = active_trade.calc_rpnl()
                    # Only set realized pnl if it isn't given by exchange implementation
                    if execution.realized_pnl is None:
                        execution.realized_pnl = rpnl - (active_trade.realized_pnl or 0)
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
                    utils.call_unknown_function(self._on_new_trade, self, trade)
                )

        await async_session.commit()

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
    @abc.abstractmethod
    async def _process_response(cls, response: ClientResponse) -> dict:
        response_json = await response.json()
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

        # OK
        if response.status == 200:
            if cls._response_result:
                return response_json[cls._response_result]
            return response_json

    @classmethod
    async def _request_handler(cls):
        while True:
            try:
                item = await cls._request_queue.get()
                request = item.request
                async with cls._session.request(request.method,
                                                request.url,
                                                params=request.params,
                                                headers=request.headers,
                                                json=request.json) as resp:

                    try:
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

    async def _request(self, method: str, path: str, headers=None, params=None, data=None, sign=True, cache=False,
                       dedupe=False, weight=None, **kwargs):
        url = self._ENDPOINT + path
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
