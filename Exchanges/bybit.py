import urllib.parse
import time
import logging
import hmac
import json
import sys
from datetime import datetime

from aiohttp import ClientResponse, ClientResponseError

from clientworker import ClientWorker
from api.dbmodels.balance import Balance
from requests import Request, Response, Session, HTTPError
from typing import List, Tuple, Dict


class BybitClient(ClientWorker):
    exchange = 'bybit'
    ENDPOINT = 'https://api.bybit.com/v2/'

    amount = float
    type = str

    # https://bybit-exchange.github.io/docs/inverse/?console#t-balance
    def _get_balance(self, time: datetime):

        request = Request(
            'GET',
            self.ENDPOINT + 'private/wallet/balance'
        )
        response = self._request(request)

        total_balance = 0
        extra_currencies: Dict[str, float] = {}
        err_msg = None
        if response['ret_code'] == 0:
            data = response['result']
            for currency in data:
                amount = float(data[currency]['equity'])
                price = 0
                if currency == 'USDT':
                    price = 1
                elif amount > 0:
                    request = Request(
                        'GET',
                        self.ENDPOINT + 'public/tickers',
                        params = {
                            'symbol': f'{currency}USD'
                        }
                    )
                    response_price = self._request(request)
                    if response_price['ret_code'] == 0:
                        price = float(response_price['result'][0]['last_price'])
                        extra_currencies[currency] = amount
                total_balance += amount * price
        else:
            err_msg = response['ret_msg']

        return Balance(amount=total_balance, currency='$', extra_currencies=extra_currencies, error=err_msg)

    # https://bybit-exchange.github.io/docs/inverse/?console#t-authentication
    def _sign_request(self, method: str, url: str, headers=None, params=None, data=None, **kwargs):
        ts = int(time.time() * 1000)
        params['api_key'] = self._api_key
        params['timestamp'] = str(ts)
        query_string = urllib.parse.urlencode(params)
        sign = hmac.new(self._api_secret.encode('utf-8'), query_string.encode('utf-8'), 'sha256').hexdigest()
        params['sign'] = sign

    async def _process_response(self, response: ClientResponse):
        response_json = await response.json()
        try:
            response.raise_for_status()
        except ClientResponseError as e:
            logging.error(f'{e}\n{response.reason}')

            error = ''
            if response.status == 400:
                error = f"400 Bad Request ({response.reason}). This is probably a bug in the bot, please contact dev"
            elif response.status == 401:
                error = f"401 Unauthorized ({response.reason}). Is your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status == 403:
                error = f"403 Access Denied ({response.reason}). Is your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status == 404:
                error = "404 Not Found. This is probably a bug in the bot, please contact dev"
            elif response.status == 429:
                error = "429 Rate Limit violated. Try again later"
            elif 500 <= response.status < 600:
                error = f"{response.status} Problem or Maintenance on {self.exchange} servers."

            # Return standard HTTP error message if status code isnt specified
            if error == '':
                error = e.args[0]

            response_json = {'ret_msg': error, 'ret_code': 1}
            return response_json

        # OK
        if response.status == 200:
            return response_json
