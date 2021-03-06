import sys
import json
import hmac
from requests import Request, Response, Session, HTTPError
import api.dbmodels.balance as balance
import urllib.parse
import time
import logging
import ccxt.async_support as ccxt
from datetime import datetime
from exchangeworker import ExchangeWorker


class OkxClient(ExchangeWorker):
    ENDPOINT = 'https://www.bitmex.com/api/v1/'

    exchange = 'okx'
    required_extra_args = ['passphrase']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ccxt_client = ccxt.okex({
            'apiKey': self._api_key,
            'secret': self._api_secret,
            'password': self._extra_kwargs['passphrase']
        })

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

        error = None
        total_balance = None

        try:
            total_balance = await self.ccxt_client.fetch_total_balance()
            tickers = await self.ccxt_client.fetch_tickers()
        except ccxt.errors.AuthenticationError:
            error = 'Unauthorized. Is your api key valid? Did you specify the right subaccount? You might want to check your API access.'
        except ccxt.errors.ExchangeError:
            error = 'This is a problem with the OKEX servers, try again later.'
        except ccxt.errors.BaseError as e:
            error = str(e)

        total = 0
        if error is None:
            for currency in total_balance:
                amount = total_balance[currency]
                price = 0
                if currency == 'USDT':
                    price = 1
                elif amount > 0:
                    price = tickers.get(f'{currency}/USDT')['last']
                total += amount * price

        return balance.Balance(amount=total, currency='$', error=error, extra_currencies={})
