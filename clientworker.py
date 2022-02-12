import abc
import logging
from datetime import datetime, timedelta
from typing import List, Callable
from urllib.request import Request
from requests import Request, Response, Session

import api.database as db
from api.dbmodels.trade import Trade
from api.dbmodels.balance import Balance
from api.dbmodels.event import Event
from api.dbmodels.client import Client


class ClientWorker:
    __tablename__ = 'client'

    exchange: str = ''
    required_extra_args: List[str] = []

    def __init__(self, client: Client):
        self.client = client
        self.client_id = client.id
        self.exchange = client.exchange

        # Client information has to be stored locally because SQL Objects aren't allowed to live in multiple threads
        self._api_key = client.api_key
        self._api_secret = client.api_secret
        self._subaccount = client.subaccount
        self._extra_kwargs = client.extra_kwargs

        self._session = Session()
        self._on_trade = None
        self._identifier = id
        self._last_fetch = datetime.fromtimestamp(0)

    def get_balance(self, time: datetime = None):
        if not time:
            time = datetime.now()
        if time - self._last_fetch < timedelta(seconds=45):
            return None
        else:
            self._last_fetch = time
        return self._get_balance(time)

    @abc.abstractmethod
    def _get_balance(self, time: datetime):
        logging.error(f'Exchange {self.exchange} does not implement _get_balance')
        raise NotImplementedError(f'Exchange {self.exchange} does not implement _get_balance')

    def set_on_trade_callback(self, callback: Callable[[int, Trade], None]):
        self._on_trade = callback

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
