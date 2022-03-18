import abc
import logging
from datetime import datetime, timedelta
from typing import List, Callable

from requests import Request, Response, Session

import api.dbmodels.client as api_client
from api.dbmodels.execution import Execution


class ClientWorker:
    __tablename__ = 'client'

    exchange: str = ''
    required_extra_args: List[str] = []

    def __init__(self, client):
        self.client = client
        self.client_id = client.id
        self.in_position = True
        self.exchange = client.exchange

        # Client information has to be stored locally because SQL Objects aren't allowed to live in multiple threads
        self._api_key = client.api_key
        self._api_secret = client.api_secret
        self._subaccount = client.subaccount
        self._extra_kwargs = client.extra_kwargs

        self._session = Session()
        self._on_execution = None
        self._identifier = id
        self._last_fetch = datetime.fromtimestamp(0)

    def get_balance(self, time: datetime = None, force=False):
        if not time:
            time = datetime.now()
        if (time - self._last_fetch < timedelta(seconds=30) or not self.in_position) and not force:
            return None
        else:
            self._last_fetch = time
        balance = self._get_balance(time)
        if not balance.time:
            balance.time = time
        return balance

    @abc.abstractmethod
    def _get_balance(self, time: datetime):
        logging.error(f'Exchange {self.exchange} does not implement _get_balance')
        raise NotImplementedError(f'Exchange {self.exchange} does not implement _get_balance')

    def set_execution_callback(self, callback: Callable[[int, Execution], None]):
        self._on_execution = callback

    @abc.abstractmethod
    def _sign_request(self, request: Request):
        logging.error(f'Exchange {self.exchange} does not implement _sign_request')

    @abc.abstractmethod
    def _process_response(self, response: Response):
        logging.error(f'Exchange {self.exchange} does not implement _process_response')

    def _request(self, request: Request, sign=True):
        if sign:
            self._sign_request(request)
        prepared = request.prepare()
        response = self._session.send(prepared)
        return self._process_response(response)

    def __repr__(self):
        return f'<Worker exchange={self.exchange} client_id={self.client_id}>'
