import base64

from models.client import Client
import hmac
from requests import Request, Response, Session, HTTPError
import urllib.parse
import time
import logging
from models.balance import Balance


class KuCoinClient(Client):
    exchange = 'kucoin'
    ENDPOINT = 'https://api-futures.kucoin.com/'

    required_extra_args = [
        'passphrase'
    ]

    # https://docs.kucoin.com/#get-account-balance-of-a-sub-account
    def get_balance(self):
        request = Request('GET', self.ENDPOINT + 'api/v1/account-overview', params={'currency': 'USDT'})
        response = self._request(request)
        if response['code'] != '200000':
            balance = Balance(0, '$', response['msg'])
        else:
            data = response['data']
            balance = Balance(amount=data['accountEquity'], currency='$', error=None)
        return balance

    # https://docs.kucoin.com/#authentication
    def _sign_request(self, request: Request):
        ts = int(time.time() * 1000)
        prepared = request.prepare()
        signature_payload = f'{ts}{request.method}{prepared.path_url}'
        if prepared.body is not None:
            signature_payload += prepared.body
        signature = base64.b64encode(
            hmac.new(self.api_secret.encode('utf-8'), signature_payload.encode('utf-8'), 'sha256').digest()
        )
        passphrase = base64.b64encode(
            hmac.new(self.api_secret.encode('utf-8'), self.extra_kwargs['passphrase'].encode('utf-8'), 'sha256').digest()
        )
        request.headers['KC-api-KEY'] = self.api_key
        request.headers['KC-api-TIMESTAMP'] = str(ts)
        request.headers['KC-api-SIGN'] = signature
        request.headers['KC-api-PASSPHRASE'] = passphrase
        request.headers['KC-api-KEY-VERSION'] = '2'

    # https://docs.kucoin.com/#request
    def _process_response(self, response: Response) -> dict:
        response_json = response.json()
        try:
            response.raise_for_status()
        except HTTPError as e:
            logging.error(f'{e}\n{response_json}')

            error = ''
            if response.status_code == 400:
                error = "400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 401:
                error = f"401 Unauthorized ({response.reason}). Is your api key valid? Did you specify the right subaccount? You might want to check your api access"
            elif response.status_code == 403:
                error = f"403 Access Denied ({response.reason}). Is your api key valid? Did you specify the right subaccount? You might want to check your api access"
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
