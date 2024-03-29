import asyncio
import urllib.parse
import time
import logging
import hmac
import json
import sys
from datetime import datetime

from aiohttp import ClientResponse, ClientResponseError

from exchangeworker import ExchangeWorker
from api.dbmodels.balance import Balance
from requests import Request, Response, Session, HTTPError
from typing import List, Tuple, Dict


class BybitClient(ExchangeWorker):
    exchange = 'bybit'
    _ENDPOINT = 'https://api.bybit.com'

    amount = float
    type = str

    # https://bybit-exchange.github.io/docs/inverse/?console#t-balance
    async def _get_balance(self, time: datetime):

        results = await asyncio.gather(
            self._get('/v2/private/wallet/balance'),
            self._get('/v2/public/tickers', sign=False, cache=True)
        )

        if isinstance(results[0], Dict):
            balance = results[0]
            tickers = results[1]
        else:
            balance = results[1]
            tickers = results[0]

        total_balance = 0.0
        extra_currencies: Dict[str, float] = {}
        err_msg = None

        if balance['ret_code'] == 0:
            data = balance['result']
            if tickers['ret_code'] == 0:
                ticker_data = tickers['result']
                ticker_prices = {
                    ticker['symbol']: ticker['last_price'] for ticker in ticker_data
                }
                for currency in data:
                    amount = float(data[currency]['equity'])
                    price = 0.0
                    if currency == 'USDT':
                        price = 1.0
                    elif amount > 0:
                        price = ticker_prices.get(f'{currency}USD') or ticker_prices.get(f'{currency}USDT')
                        extra_currencies[currency] = amount
                        if not price:
                            logging.info(f'Bybit Bug: ticker prices do not contain info about {currency}:\n{ticker_prices}')
                            continue
                    total_balance += amount * float(price)
            else:
                err_msg = tickers['ret_msg']
        else:
            err_msg = balance['ret_msg']

        return Balance(amount=total_balance, currency='$', extra_currencies=extra_currencies, error=err_msg)

    # https://bybit-exchange.github.io/docs/inverse/?console#t-authentication
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
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
