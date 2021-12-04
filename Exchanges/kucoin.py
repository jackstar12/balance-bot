import base64

from client import Client
import hmac
from requests import Request, Response, Session, HTTPError
import urllib.parse
import time
import logging


class KuCoinClient(Client):
    exchange = 'kucoin'
    ENDPOINT = 'https://api.kucoin.com/'

    # https://docs.kucoin.com/#get-account-balance-of-a-sub-account
    def getBalance(self):
        s = Session()
        request = Request('GET', self.ENDPOINT + 'api/v1/accounts')
        self._sign_request(request)
        response = s.send(request.prepare())
        return self._process_response(response)

    def _sign_request(self, request: Request):
        ts = int(time.time() * 1000)
        prepared = request.prepare()
        signature_payload = f'{ts}{request.method}{prepared.path_url}{request.json}'
        signature = hmac.new(self.api_secret.encode('utf-8'), signature_payload.encode('utf-8'), 'sha256').hexdigest()
        passphrase = base64.b64encode(
            hmac.new(self.api_secret.encode('utf-8'), self.api_passphrase.encode('utf-8'), 'sha256').digest()
        )
        request.headers['KC-API-KEY'] = self.api_key
        request.headers['KC-API-TIMESTAMP'] = ts
        request.headers['KC-API-SIGN'] = signature
        request.headers['KC-API-PASSPHRASE'] = passphrase  # TODO: Implement optional extra user info
        request.headers['KC-API-KEY-VERSION'] = ''

    # https://docs.kucoin.com/#request
    def _process_response(self, response: Response) -> str:
        try:
            response.raise_for_status()
        except HTTPError as e:
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

        # OK
        if response.status_code == 200:
            return str(response.json()['totalCrossWalletBalance']) + '$'
