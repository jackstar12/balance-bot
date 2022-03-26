import abc
import logging
from datetime import datetime, timedelta
from typing import List, Callable, Union, Dict
import aiohttp.client
from aiohttp import ClientResponse
from typing import NamedTuple
from requests import Request, Response, Session

from api.dbmodels.execution import Execution
from api.dbmodels.client import Client
from api.dbmodels.balance import Balance


class Cached(NamedTuple):
    url: str
    response: dict
    expires: datetime


class ClientWorker:
    __tablename__ = 'client'
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
        self._on_execution = None
        self._identifier = id
        self._last_fetch = datetime.fromtimestamp(0)

    async def get_balance(self, session, time: datetime = None, force=False):
        if not time:
            time = datetime.now()
        if force or (time - self._last_fetch > timedelta(seconds=30) and not self.client.rekt_on):
            self._last_fetch = time
            balance = await self._get_balance(time)
            if not balance.time:
                balance.time = time
            balance.client_id = self.client_id
            return balance
        elif self.client.rekt_on:
            return Balance(amount=0.0, currency='$', extra_currencies={}, error=None, time=time)
        else:
            return None

    @abc.abstractmethod
    async def _get_balance(self, time: datetime):
        logging.error(f'Exchange {self.exchange} does not implement _get_balance')
        raise NotImplementedError(f'Exchange {self.exchange} does not implement _get_balance')

    def set_execution_callback(self, callback: Callable[[int, Execution], None]):
        self._on_execution = callback

    @abc.abstractmethod
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        logging.error(f'Exchange {self.exchange} does not implement _sign_request')

    @abc.abstractmethod
    async def _process_response(self, response: ClientResponse):
        logging.error(f'Exchange {self.exchange} does not implement _process_response')

    async def _request(self, method: str, path: str, headers=None, params=None, data=None, sign=True, cache=False, **kwargs):
        headers = headers or {}
        params = params or {}
        url = self._ENDPOINT + path
        if cache:
            cached = ClientWorker._cache.get(url)
            if cached and datetime.now() < cached.expires:
                return cached.response
        if sign:
            self._sign_request(method, path, headers, params, data)
        async with self._session.request(method, url, headers=headers, params=params, data=data, **kwargs) as resp:
            resp = await self._process_response(resp)
            if cache:
                ClientWorker._cache[url] = Cached(
                    url=url,
                    response=resp,
                    expires=datetime.now() + timedelta(seconds=5)
                )
            return resp

    async def _get(self, path: str, **kwargs):
        return await self._request('GET', path, **kwargs)

    async def _post(self, path: str, **kwargs):
        return await self._request('POST', path, **kwargs)

    async def _put(self, path: str, **kwargs):
        return await self._request('PUT', path, **kwargs)

    def __repr__(self):
        return f'<Worker exchange={self.exchange} client_id={self.client_id}>'
