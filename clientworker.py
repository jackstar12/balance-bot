import abc
import logging
from typing import List, Callable
from urllib.request import Request
from requests import Request, Response, Session

from api.database import db
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
        self._session = Session()
        self._on_trade = None
        self._identifier = id

    @abc.abstractmethod
    def get_balance(self):
        logging.error(f'Exchange {self.exchange} does not implement get_balance')

    def on_trade(self, callback: Callable[[str, Trade], None], identifier):
        self._on_trade = callback
        self._identifier = identifier

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
        return f'<Client exchange={self.exchange} user_id={self.user_id}>'
