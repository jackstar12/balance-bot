import hmac
from requests import Request, Response, Session, HTTPError
from api.dbmodels.balance import Balance
import urllib.parse
import time
import logging
from datetime import datetime
from clientworker import ClientWorker


class BitmexClient(ClientWorker):
    exchange = 'bitmex'
    ENDPOINT = 'https://www.bitmex.com/api/v1/'

    # https://www.bitmex.com/api/explorer/#!/User/User_getWallet
    def _get_balance(self, time: datetime):
        # Could do something like that for displaying a trade history
        # request = Request(
        #     'GET',
        #     self.ENDPOINT + 'execution/tradeHistory',
        #     params={
        #         'startTime': str(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
        #     }
        # )
        # res = self._request(request)
        request = Request(
            'GET',
            self.ENDPOINT + 'user/wallet',
            params={'currency': 'all'}
        )
        response = self._request(request)
        total_balance = 0
        extra_currencies = {}
        err_msg = None
        if 'error' not in response:
            for currency in response:
                symbol = currency['currency'].upper()
                amount = currency['amount']
                price = 0
                if symbol == 'USDT':
                    price = 1
                elif amount > 0:
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
                            amount *= 10**-8
                        extra_currencies[symbol] = amount
                total_balance += amount * price
        else:
            err_msg = response['error']

        return Balance(amount=total_balance,
                       currency='$',
                       extra_currencies=extra_currencies,
                       error=err_msg)

    # https://www.bitmex.com/app/apiKeysUsage
    def _sign_request(self, request: Request):
        ts = int(time.time() * 1000)
        prepared = request.prepare()
        request_signature = f'{prepared.method}{prepared.path_url}{ts}'
        if prepared.body is not None:
            request_signature += prepared.body

        signature = hmac.new(self._api_secret.encode(), request_signature.encode(), 'sha256').hexdigest()

        request.headers['api-expires'] = str(ts)
        request.headers['api-key'] = self._api_key
        request.headers['api-signature'] = signature

    def _process_response(self, response: Response):
        response_json = response.json()
        try:
            response.raise_for_status()
        except HTTPError as e:
            logging.error(f'{e}\n{response_json}')

            error = ''
            if response.status_code == 400:
                error = "400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 401:
                error = f"401 Unauthorized ({response.reason}). Is your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status_code == 403:
                error = f"403 Access Denied ({response.reason}). Is your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status_code == 404:
                error = "404 Not Found. This is probably a bug in the bot, please contact dev"
            elif response.status_code == 429:
                error = "429 Rate Limit violated. Try again later"
            elif 500 <= response.status_code < 600:
                error = f"{response.status_code} Problem or Maintenance on {self.exchange} servers."

            # Return standard HTTP error message if status code isnt specified
            if error == '':
                error = e.args[0]

            response_json['error'] = error
            return response_json

        # OK
        if response.status_code == 200:
            return response_json
