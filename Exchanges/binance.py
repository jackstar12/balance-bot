import hmac
import hmac
import logging
import time
import urllib.parse
from typing import Dict, Callable

import requests
from requests import Request, HTTPError

from Models.balance import Balance
from Models.client import Client


class _BinanceBaseClient(Client):

    def _sign_request(self, request: Request) -> None:
        ts = int(time.time() * 1000)
        request.headers['X-MBX-APIKEY'] = self.api_key
        request.params['timestamp'] = ts
        query_string = urllib.parse.urlencode(request.params, True)
        signature = hmac.new(self.api_secret.encode(), query_string.encode(), 'sha256').hexdigest()
        request.params['signature'] = signature

    def _process_response(self, response: requests.Response) -> dict:
        response_json = response.json()
        try:
            response.raise_for_status()
        except HTTPError as e:
            logging.error(f'{e}\n{response_json=}\n{response.reason=}')

            error = ''
            if response.status_code == 400:
                error = "400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 401:
                error = f"401 Unauthorized ({response.reason}). You might want to check your API access"
            elif response.status_code == 403:
                error = f"403 Access Denied ({response.reason}). You might want to check your API access"
            elif response.status_code == 404:
                error = "404 Not Found. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 429:
                error = "429 Rate Limit violated. Try again later"
            elif 500 <= response.status_code < 600:
                error = f"{response.status_code} Problem or Maintenance on {self.exchange} servers."

            response_json['msg'] = error
            return response_json

        # OK
        if response.status_code == 200:
            return response_json


class BinanceFutures(_BinanceBaseClient):
    ENDPOINT = 'https://fapi.binance.com/'
    exchange = 'binance-futures'

    # https://binance-docs.github.io/apidocs/futures/en/#account-information-v2-user_data
    def get_balance(self):
        request = Request('GET', self.ENDPOINT + 'fapi/v2/account')
        response = self._request(request)

        return Balance(amount=float(response.get('totalMarginBalance', 0)), currency='$', error=response.get('msg', None))


class BinanceSpot(_BinanceBaseClient):
    ENDPOINT = 'https://api.binance.com/api/v3/'
    exchange = 'binance-spot'

    # https://binance-docs.github.io/apidocs/spot/en/#account-information-user_data
    def get_balance(self):
        request = Request('GET', self.ENDPOINT + 'account')
        response = self._request(request)
        logging.info(f'Binance Spot response {response}')
        total_balance = 0
        extra_currencies: Dict[str, float] = {}
        err_msg = None
        if response.get('msg') is None:
            data = response['balances']
            for balance in data:
                currency = balance['asset']
                amount = float(balance['free']) + float(balance['locked'])
                price = 0
                if currency == 'USDT':
                    price = 1
                elif amount > 0:
                    request = Request(
                        'GET',
                        self.ENDPOINT + 'ticker/price',
                        params={
                            'symbol': f'{currency}USDT'
                        }
                    )
                    response_price = self._request(request, sign=False)
                    if response_price.get('msg') is None:
                        price = float(response_price['price'])
                total_balance += amount * price
        else:
            err_msg = response['msg']

        return Balance(amount=total_balance, currency='$', extra_currencies=extra_currencies, error=err_msg)
