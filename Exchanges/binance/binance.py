from __future__ import annotations
from typing import NamedTuple

import asyncio
import hmac
import hmac
import json
import logging
import time
import urllib.parse
from datetime import datetime
from typing import Dict, Callable

import requests
from aiohttp import ClientResponse, ClientResponseError
from requests import Request, HTTPError
from exchangeworker import ExchangeWorker
from api.dbmodels.client import Client
import api.dbmodels.balance as balance


class _BinanceBaseClient(ExchangeWorker):

    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs) -> None:
        ts = int(time.time() * 1000)
        headers['X-MBX-APIKEY'] = self._api_key
        params['timestamp'] = ts
        query_string = urllib.parse.urlencode(params, True)
        signature = hmac.new(self._api_secret.encode(), query_string.encode(), 'sha256').hexdigest()
        params['signature'] = signature

    async def _process_response(self, response: ClientResponse) -> dict:
        response_json = await response.json()
        try:
            response.raise_for_status()
        except ClientResponseError as e:
            logging.error(f'{e}\n{response_json=}\n{response.reason=}')

            error = ''
            if response.status == 400:
                error = "400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status == 401:
                error = f"401 Unauthorized ({response.reason}). You might want to check your API access"
            elif response.status == 403:
                error = f"403 Access Denied ({response.reason}). You might want to check your API access"
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


class _TickerCache(NamedTuple):
    ticker: dict
    time: datetime


class BinanceFutures(_BinanceBaseClient):
    _ENDPOINT = 'https://fapi.binance.com'
    exchange = 'binance-futures'

    # https://binance-docs.github.io/apidocs/futures/en/#account-information-v2-user_data
    async def _get_balance(self, time: datetime = None):
        response = await self._get('/fapi/v2/account')

        usd_assets = [
            asset for asset in response["assets"] if asset["asset"] in ("USDT", "BUSD")
        ]

        return balance.Balance(
            amount=sum(
                float(asset.get('marginBalance', 0))
                for asset in usd_assets
            ),
            currency='$',
            time=time if time else datetime.now(),
            error=response.get('msg', None)
        )


class BinanceSpot(_BinanceBaseClient):

    _ENDPOINT = 'https://api.binance.com/api/v3'
    exchange = 'binance-spot'

    # https://binance-docs.github.io/apidocs/spot/en/#account-information-user_data
    async def _get_balance(self, time: datetime):

        results = await asyncio.gather(
            self._get('/account'),
            self._get('/ticker/price', sign=False, cache=True)
        )

        if isinstance(results[0], dict):
            response = results[0]
            tickers = results[1]
        else:
            response = results[1]
            tickers = results[0]

        total_balance = 0
        extra_currencies: Dict[str, float] = {}
        err_msg = None

        if response.get('msg') is None:
            data = response['balances']
            ticker_prices = {
                ticker['symbol']: ticker['price'] for ticker in tickers
            }
            for cur_balance in data:
                currency = cur_balance['asset']
                amount = float(cur_balance['free']) + float(cur_balance['locked'])
                price = 0
                if currency == 'USDT':
                    price = 1
                elif amount > 0 and currency != 'LDUSDT' and currency != 'LDSRM':
                    price = float(ticker_prices.get(f'{currency}USDT', 0))
                total_balance += amount * price
        else:
            err_msg = response['msg']

        return balance.Balance(amount=total_balance, currency='$', extra_currencies=extra_currencies, error=err_msg)
