import dataclasses
import hmac
import json
import sys
import urllib.parse
import requests
import logging
import time

from balance import Balance
from requests import Session, Request, Response, HTTPError

from client import Client


class BinanceClient(Client):
    ENDPOINT = 'https://fapi.binance.com/'
    exchange = 'binance'

    # https://binance-docs.github.io/apidocs/futures/en/#account-information-v2-user_data
    def getBalance(self):
        s = Session()
        request = Request('GET', self.ENDPOINT + 'fapi/v2/account')
        self._sign_request(request)
        prepared = request.prepare()
        response = self._process_response(s.send(prepared))

        return Balance(amount=float(response.get('totalWalletBalance', 0)), currency='$', error=response.get('msg', None))

    def _sign_request(self, request: Request) -> None:
        ts = int(time.time() * 1000)
        request.headers['X-MBX-APIKEY'] = self.api_key
        request.params['timestamp'] = ts

        query_string = urllib.parse.urlencode(request.params, True)
        signature = hmac.new(self.api_secret.encode(), query_string.encode(), 'sha256').hexdigest()
        request.params['signature'] = signature

        # TODO: Binance subaccounts?
        if self.subaccount:
            pass

    def _process_response(self, response: requests.Response) -> dict:
        response_json = response.json()
        try:
            response.raise_for_status()
        except HTTPError as e:
            logging.error(f'{e}+\n{e.response}')

            error = ''
            if response.status_code == 400:
                error = "400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 401:
                error = "401 Unauthorized. You might want to check your API access with <prefix> info"
            elif response.status_code == 403:
                error = "403 Access Denied. You might want to check your API access with <prefix> info"
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

