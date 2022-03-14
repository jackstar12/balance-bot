import urllib.parse
import hmac
import logging
from datetime import datetime
from typing import List, Callable

from api.dbmodels.execution import Execution
import api.dbmodels.balance as balance
from clientworker import ClientWorker
import time
import requests
from requests import Request, Session

from Exchanges.ftx.client import FtxWebsocketClient


class FtxClient(ClientWorker):
    exchange = 'ftx'
    ENDPOINT = 'https://ftx.com/api/'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ws = FtxWebsocketClient(api_key=self._api_key,
                                     api_secret=self._api_secret,
                                     subaccount=self._subaccount,
                                     on_message_callback=self._on_message)

    def set_execution_callback(self, callback: Callable[[int, Execution], None]):
        super().set_execution_callback(callback)
        self.ws.connect()
        self.ws.get_fills()

    def _on_message(self, ws, message):
        if message['channel'] == 'fills':
            if callable(self._on_execution):
                self._on_execution(
                    self.client_id,
                    Execution(
                        symbol=message['market'],
                        side=message['side'],
                        price=float(message['price']),
                        qty=float(message['size']),
                        time=datetime.now()
                    )
                )

    # https://docs.ftx.com/#account
    def _get_balance(self, time: datetime):
        request = Request(
            'GET',
            self.ENDPOINT + 'account'
        )
        response = self._request(request)
        if response['success']:
            amount = response['result']['totalAccountValue']
        else:
            amount = 0
        return balance.Balance(amount=amount, currency='$', error=response.get('error'), time=time)

    def _sign_request(self, request: Request) -> None:
        ts = int(time.time() * 1000)
        prepared = request.prepare()
        signature_payload = f'{ts}{prepared.method}{prepared.path_url}'.encode()
        if prepared.body:
            signature_payload += prepared.body
        signature = hmac.new(self._api_secret.encode(), signature_payload, 'sha256').hexdigest()
        request.headers['FTX-KEY'] = self._api_key
        request.headers['FTX-SIGN'] = signature
        request.headers['FTX-TS'] = str(ts)
        if self._subaccount:
            request.headers['FTX-SUBACCOUNT'] = urllib.parse.quote(self._subaccount)

    def _process_response(self, response: requests.Response) -> dict:
        response_json = response.json()
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            logging.error(f'{e}\n{response_json}')

            error = ''
            if response.status_code == 400:
                error = f"400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 401:
                error = f"401 Unauthorized ({response_json['error']}).\nIs your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status_code == 403:
                error = f"403 Access Denied ({response_json['error']}).\nIs your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status_code == 404:
                error = f"404 Not Found. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 429:
                error = f"429 Rate Limit violated. Try again later"
            elif 500 <= response.status_code < 600:
                error = f"{response.status_code} ({response_json['error']}).\nProblem or Maintenance on {self.exchange} servers."

            response_json['error'] = error
            return response_json

        if response.status_code == 200:
            return response_json


