from __future__ import annotations
import hmac
import hmac
import json
import logging
import sys
import time
import urllib.parse
from datetime import datetime
from typing import Dict, Callable

import requests
from requests import Request, HTTPError
from Exchanges.binance.futures_websocket_client import FuturesWebsocketClient
from clientworker import ClientWorker
from api.dbmodels.client import Client
import api.dbmodels.balance as balance
from api.dbmodels.execution import Execution


class _BinanceBaseClient(ClientWorker):

    def _sign_request(self, request: Request) -> None:
        ts = int(time.time() * 1000)
        request.headers['X-MBX-APIKEY'] = self._api_key
        request.params['timestamp'] = ts
        query_string = urllib.parse.urlencode(request.params, True)
        signature = hmac.new(self._api_secret.encode(), query_string.encode(), 'sha256').hexdigest()
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

    def start_user_stream(self):
        return None

    def keep_alive(self, listenKey):
        pass


class BinanceFutures(_BinanceBaseClient):
    ENDPOINT = 'https://fapi.binance.com/'
    exchange = 'binance-futures'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ws = FuturesWebsocketClient(self, self._on_message)

    # https://binance-docs.github.io/apidocs/futures/en/#account-information-v2-user_data
    def _get_balance(self, time: datetime = None):
        request = Request('GET', self.ENDPOINT + 'fapi/v2/account')
        response = self._request(request)

        return balance.Balance(amount=float(response.get('totalMarginBalance', 0)), currency='$', time=time if time else datetime.now(), error=response.get('msg', None))

    def start_user_stream(self):
        request = Request(
            method='POST',
            url=self.ENDPOINT + 'fapi/v1/listenKey'
        )
        response = self._request(request)
        if response.get('msg') is None:
            return response['listenKey']
        else:
            return None

    def keep_alive(self, listenKey):
        request = Request(
            method='PUT',
            url=self.ENDPOINT + 'fapi/v1/listenKey'
        )
        self._request(request)

    def set_execution_callback(self, callback: Callable[[Client, Execution], None]):
        self._callback = callback
        self._ws.start()

    def _on_message(self, ws, message):
        message = json.loads(message)
        event = message['e']
        data = message['o']
        if event == 'ORDER_TRADE_UPDATE':
            if data['X'] == 'FILLED' or True:
                json.dump(data, fp=sys.stdout, indent=3)
                trade = Execution(
                    symbol=data['s'],
                    price=float(data['ap']) or float(data['p']),
                    qty=float(data['q']),
                    side=data['S'],
                    time=datetime.now()
                )
                if callable(self._callback):
                    self._callback(self.client_id, trade)


class BinanceSpot(_BinanceBaseClient):
    ENDPOINT = 'https://api.binance.com/api/v3/'
    exchange = 'binance-spot'

    # https://binance-docs.github.io/apidocs/spot/en/#account-information-user_data
    def _get_balance(self, time: datetime):
        request = Request('GET', self.ENDPOINT + 'account')
        response = self._request(request)

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
                elif amount > 0 and currency != 'LDUSDT' and currency != 'LDSRM':
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
                if amount * price > 0.05:
                    total_balance += amount * price
        else:
            err_msg = response['msg']

        return balance.Balance(amount=total_balance, currency='$', extra_currencies=extra_currencies, error=err_msg)
