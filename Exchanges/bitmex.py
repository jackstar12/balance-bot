import hmac
from client import Client
from requests import Request, Response, Session, HTTPError
import urllib.parse
import time
import logging


class BitmexClient(Client):
    exchange = 'bitmex'
    ENDPOINT = 'https://www.bitmex.com/api/v1/'

    # https://www.bitmex.com/api/explorer/#!/User/User_getWallet
    def getBalance(self):
        s = Session()
        request = Request('GET', self.ENDPOINT + 'user/wallet')
        self._sign_request(request)
        response = s.send(request.prepare())
        return self._process_response(response)

    # https://www.bitmex.com/app/apiKeysUsage
    def _sign_request(self, request: Request):
        ts = int(time.time() * 1000)
        prepared = request.prepare()
        request.headers['api-expires'] = str(ts)
        request.headers['api-key'] = self.api_key
        signature_payload = f'{prepared.method}{prepared.path_url}{ts}{prepared.body if prepared.body is not None else ""}'
        signature = hmac.new(self.api_secret.encode(), signature_payload.encode(), 'sha256').hexdigest()
        request.headers['api-signature'] = signature

    def _process_response(self, response: Response) -> str:
        try:
            response.raise_for_status()
        except HTTPError as e:
            logging.error(e)
            if response.status_code == 400:
                return "400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 401:
                return "401 Unauthorized. You might want to check your API access with <prefix> info"
            elif response.status_code == 403:
                return "403 Access Denied. You might want to check your API access with <prefix> info"
            elif response.status_code == 404:
                return "404 Not Found. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 429:
                return "429 Rate Limit violated. Try again later"
            elif 500 <= response.status_code < 600:
                return f"{response.status_code} Problem or Maintenance on {self.exchange} servers."

            # Return standard HTTP error message if status code isnt specified
            return e.args[0]

        # OK
        if response.status_code == 200:
            response_json = response.json()
            return str(round(response_json['amount'] * 10**-8, ndigits=5)) + response_json['currency']
