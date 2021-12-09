import hmac
from client import Client
from requests import Request, Response, Session, HTTPError
from balance import Balance
import urllib.parse
import time
import logging


class BitmexClient(Client):
    exchange = 'bitmex'
    ENDPOINT = 'https://www.bitmex.com/api/v1/'

    # https://www.bitmex.com/api/explorer/#!/User/User_getWallet
    def get_balance(self):
        request = Request(
            'GET',
            self.ENDPOINT + 'user/wallet',
            params={'currency': 'all'}
        )
        response = self._request(request)
        total_balance = 0
        err_msg = None
        if 'error' not in response:
            for currency in response:
                symbol = currency['currency'].upper()
                price = 0
                if symbol == 'USDT':
                    price = 1
                else:
                    request = Request(
                        'GET',
                        self.ENDPOINT + 'trade',
                        params = {
                            'symbol': symbol.upper(),
                            'count': 1,
                            'reverse': True
                        }
                    )
                    response_price = self._request(request)
                    if len(response_price) > 0:
                        price = response_price[0]['price']
                        if 'XBT' in symbol:
                            # XBT amount is given in Sats (100 Million Sats = 1BTC)
                            price *= 10**-8
                total_balance += currency['amount'] * price
        else:
            err_msg = response['error']
        return Balance(total_balance, '$', err_msg)

    def _request(self, request: Request):
        s = Session()
        self._sign_request(request)
        prepared = request.prepare()
        response = s.send(prepared)
        return self._process_response(response)

    # https://www.bitmex.com/app/apiKeysUsage
    def _sign_request(self, request: Request):
        ts = int(time.time() * 1000)
        prepared = request.prepare()
        request.headers['api-expires'] = str(ts)
        request.headers['api-key'] = self.api_key
        signature_payload = f'{prepared.method}{prepared.path_url}{ts}'
        if prepared.body is not None:
            signature_payload += prepared.body
        signature = hmac.new(self.api_secret.encode(), signature_payload.encode(), 'sha256').hexdigest()
        request.headers['api-signature'] = signature

    def _process_response(self, response: Response):
        try:
            response.raise_for_status()
        except HTTPError as e:
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

            # Return standard HTTP error message if status code isnt specified
            if error == '':
                error = e.args[0]

            response_json = response.json()
            response_json['error'] = error
            return response_json

        # OK
        if response.status_code == 200:
            response_json = response.json()
            return response_json
