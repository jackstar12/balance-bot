import hmac

from aiohttp import ClientResponse, ClientResponseError
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
    async def _get_balance(self, time: datetime):
        # Could do something like that for displaying a trade history
        # request = Request(
        #     'GET',
        #     self.ENDPOINT + 'execution/tradeHistory',
        #     params={
        #         'startTime': str(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
        #     }
        # )
        # res = self._request(request)
        response = await self._get(
            self.ENDPOINT + 'user/wallet',
            params={'currency': 'all'}
        )
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
                    response_price = await self._get(
                        self.ENDPOINT + 'trade',
                        params={
                            'symbol': symbol.upper(),
                            'count': 1,
                            'reverse': True
                        }
                    )
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
    def _sign_request(self, method: str, url: str, headers=None, params=None, data=None, **kwargs):
        ts = int(time.time() * 1000)
        request_signature = f'{method}{url}{ts}'
        if data is not None:
            request_signature += data
        signature = hmac.new(self._api_secret.encode(), request_signature.encode(), 'sha256').hexdigest()
        headers['api-expires'] = str(ts)
        headers['api-key'] = self._api_key
        headers['api-signature'] = signature

    async def _process_response(self, response: ClientResponse):
        response_json = await response.json()
        try:
            response.raise_for_status()
        except ClientResponseError as e:
            logging.error(f'{e}\n{response_json}')

            error = ''
            if response.status == 400:
                error = "400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status == 401:
                error = f"401 Unauthorized ({response.reason}). Is your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status == 403:
                error = f"403 Access Denied ({response.reason}). Is your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status == 404:
                error = "404 Not Found. This is probably a bug in the bot, please contact dev"
            elif response.status == 429:
                error = "429 Rate Limit violated. Try again later"
            elif 500 <= response.status < 600:
                error = f"{response.status} Problem or Maintenance on {self.exchange} servers."

            # Return standard HTTP error message if status code isnt specified
            if error == '':
                error = e.args[0]

            response_json['error'] = error
            return response_json

        # OK
        if response.status == 200:
            return response_json
