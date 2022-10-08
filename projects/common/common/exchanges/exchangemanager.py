from __future__ import annotations
import asyncio
import logging
import time
import urllib.parse
from asyncio import Future, Task
from datetime import datetime
from enum import Enum
from typing import List, Callable, Dict, Optional, Union, Set
import aiohttp.client
import pytz
from aiohttp import ClientResponse, ClientResponseError
from typing import NamedTuple
from asyncio.queues import PriorityQueue

from common.dbmodels.execution import Execution

from common.enums import Priority
from common.errors import RateLimitExceeded, ExchangeUnavailable, ExchangeMaintenance, ResponseError
from common.messenger import TableNames, Messenger

from common.dbmodels.client import Client
from typing import TYPE_CHECKING

from common.exchanges.exchangeworker import ExchangeWorker

if TYPE_CHECKING:
    pass

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
