import dataclasses
import hmac
import json
import sys
import urllib.parse
import requests
import logging
import time

from requests import Session, Request, Response

from client import Client


@dataclasses.dataclass
class BinanceClient(Client):
    ENDPOINT = 'https://fapi.binance.com/'
    exchange = 'binance'

    def getBalance(self):
        s = Session()
        request = Request('GET', self.ENDPOINT + 'fapi/v2/account')
        self._sign_request(request)
        prepared = request.prepare()
        response = s.send(prepared)
        return self._process_response(response)

    def _sign_request(self, request: Request) -> None:
        ts = int(time.time() * 1000)
        request.params['timestamp'] = ts
        request.headers['X-MBX-APIKEY'] = self.api_key
        query_string = urllib.parse.urlencode(request.params, True)
        signature = hmac.new(self.api_secret.encode(), query_string.encode(), 'sha256').hexdigest()
        request.params['signature'] = signature
        if self.subaccount:
            pass
            #request.headers['FTX-SUBACCOUNT'] = urllib.parse.quote(self.subaccount)

    def _process_response(self, response: requests.Response) -> str:
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            logging.error(e)
            if response.status_code == 400:
                return "400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 401:
                return "401 Unauthorized. You might want to check your API access with <prefix> info"
            elif response.status_code == 429:
                return "429 Rate Limit violated. Try again later"
            elif 500 <= response.status_code < 600:
                return f"Problem with {self.exchange} servers."

            # Return standard HTTP error message if status code isnt specified
            return e.args[0]

        if response.status_code == 200:
            return str(response.json()['totalCrossWalletBalance']) + '$'

