import urllib
import hmac
import logging
from logging import getLogger

from fastapi import requests

from client import Client
import time
import requests
from requests import Request, Session


class FtxClient(Client):
    exchange = 'ftx'
    ENDPOINT = 'https://ftx.com/api/'

    def getBalance(self):
        s = Session()
        request = Request('GET', self.ENDPOINT + 'account')
        self._sign_request(request)
        response = s.send(request.prepare())
        return self._process_response(response)

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

    def _process_response(self, response: requests.Response) -> str:
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            logging.error(e)
            if response.status_code == 400:
                return "400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 401:
                return "401 Unauthorized. You might want to check your API access with <prefix> info"
            elif 500 <= response.status_code < 600:
                return f"Problem with {self.exchange} servers."

            # Return HTTP Error Message
            return e.args[0]

        if response.status_code == 200:
            return str(response.json()['result']['totalAccountValue']) + '$'


