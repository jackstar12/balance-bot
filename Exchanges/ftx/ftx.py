import urllib.parse
import hmac
import logging
from datetime import datetime
from typing import Callable
from aiohttp import ClientResponse, ClientResponseError
import api.dbmodels.balance as balance
from clientworker import ClientWorker
import time
import requests
from requests import Request, Session


class FtxClient(ClientWorker):
    exchange = 'ftx'
    _ENDPOINT = 'https://ftx.com'

    # https://docs.ftx.com/#account
    async def _get_balance(self, time: datetime):
        response = await self._get('/api/account')
        if response['success']:
            amount = response['result']['totalAccountValue']
        else:
            amount = 0
        return balance.Balance(amount=amount, currency='$', error=response.get('error'), time=time)

    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs) -> None:
        ts = int(time.time() * 1000)
        signature_payload = f'{ts}{method}{path}'.encode()
        if data:
            signature_payload += data
        signature = hmac.new(self._api_secret.encode(), signature_payload, 'sha256').hexdigest()
        headers['FTX-KEY'] = self._api_key
        headers['FTX-SIGN'] = signature
        headers['FTX-TS'] = str(ts)
        if self._subaccount:
            headers['FTX-SUBACCOUNT'] = urllib.parse.quote(self._subaccount)

    async def _process_response(self, response: ClientResponse) -> dict:
        response_json = await response.json()
        try:
            response.raise_for_status()
        except ClientResponseError as e:
            logging.error(f'{e}\n{response_json}')

            error = ''
            if response.status == 400:
                error = f"400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status == 401:
                error = f"401 Unauthorized ({response_json['error']}).\nIs your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status == 403:
                error = f"403 Access Denied ({response_json['error']}).\nIs your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status == 404:
                error = f"404 Not Found. This is probably a bug in the bot, please contact dev"
            elif response.status == 429:
                error = f"429 Rate Limit violated. Try again later"
            elif 500 <= response.status < 600:
                error = f"{response.status} ({response_json['error']}).\nProblem or Maintenance on {self.exchange} servers."

            response_json['error'] = error
            return response_json

        if response.status == 200:
            return response_json


