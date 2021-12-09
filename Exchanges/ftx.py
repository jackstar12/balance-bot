import urllib.parse
import hmac
import logging
from logging import getLogger
from fastapi import requests
from client import Client
from balance import Balance
import time
import requests
from requests import Request, Session


class FtxClient(Client):
    exchange = 'ftx'
    ENDPOINT = 'https://ftx.com/api/'

    def get_balance(self):
        s = Session()
        request = Request('GET', self.ENDPOINT + 'account')
        self._sign_request(request)
        response = s.send(request.prepare())
        response = self._process_response(response)
        if response['success']:
            amount = response['result']['totalAccountValue']
        else:
            amount = 0
        return Balance(amount, '$', response.get('error'))

    def _sign_request(self, request: Request) -> None:
        ts = int(time.time() * 1000)
        prepared = request.prepare()
        signature_payload = f'{ts}{prepared.method}{prepared.path_url}'.encode()
        if prepared.body:
            signature_payload += prepared.body
        signature = hmac.new(self.api_secret.encode(), signature_payload, 'sha256').hexdigest()
        request.headers['FTX-KEY'] = self.api_key
        request.headers['FTX-SIGN'] = signature
        request.headers['FTX-TS'] = str(ts)
        if self.subaccount:
            request.headers['FTX-SUBACCOUNT'] = urllib.parse.quote(self.subaccount)

    def _process_response(self, response: requests.Response) -> dict:
        response_json = response.json()
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            logging.error(f'{e}\n{response_json}')

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

            response_json['error'] = error
            return response_json

        if response.status_code == 200:
            return response_json


