import base64

import hmac
from datetime import datetime

from aiohttp import ClientResponse, ClientResponseError
from requests import Request, Response, Session, HTTPError
import urllib.parse
import time
import logging
from clientworker import ClientWorker
from api.dbmodels.balance import Balance


class KuCoinClient(ClientWorker):
    exchange = 'kucoin'
    _ENDPOINT = 'https://api-futures.kucoin.com'

    required_extra_args = [
        'passphrase'
    ]

    # https://docs.kucoin.com/#get-account-balance-of-a-sub-account
    async def _get_balance(self, time: datetime):
        response = await self._get(
            '/api/v1/account-overview',
            params={'currency': 'USDT'}
        )
        if response['code'] != '200000':
            balance = Balance(amount=0, currency='$', error=response['msg'])
        else:
            data = response['data']
            balance = Balance(amount=data['accountEquity'], currency='$', error=None)
        return balance

    # https://docs.kucoin.com/#authentication
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        ts = int(time.time() * 1000)
        signature_payload = f'{ts}{method}{path}{self._query_string(params)}'
        if data is not None:
            signature_payload += data
        signature = base64.b64encode(
            hmac.new(self._api_secret.encode('utf-8'), signature_payload.encode('utf-8'), 'sha256').digest()
        ).decode()
        passphrase = base64.b64encode(
            hmac.new(self._api_secret.encode('utf-8'), self._extra_kwargs['passphrase'].encode('utf-8'), 'sha256').digest()
        ).decode()
        headers['KC-API-KEY'] = self._api_key
        headers['KC-API-TIMESTAMP'] = str(ts)
        headers['KC-API-SIGN'] = signature
        headers['KC-API-PASSPHRASE'] = passphrase
        headers['KC-API-KEY-VERSION'] = '2'

    # https://docs.kucoin.com/#request
    async def _process_response(self, response: ClientResponse) -> dict:
        response_json = await response.json()
        try:
            response.raise_for_status()
        except ClientResponseError as e:
            logging.error(f'{e}\n{response_json}')

            error = ''
            if response.status == 400:
                error = "400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status == 401:
                error = f"401 Unauthorized ({response.reason}). Is your api key valid? Did you specify the right subaccount? You might want to check your api access"
            elif response.status == 403:
                error = f"403 Access Denied ({response.reason}). Is your api key valid? Did you specify the right subaccount? You might want to check your api access"
            elif response.status == 404:
                error = "404 Not Found. This is probably a bug in the bot, please contact dev"
            elif response.status == 429:
                error = "429 Rate Limit violated. Try again later"
            elif 500 <= response.status < 600:
                error = f"{response.status} Problem or Maintenance on {self.exchange} servers."

            response_json['msg'] = error
            return response_json

        # OK
        if response.status == 200:
            return response_json
