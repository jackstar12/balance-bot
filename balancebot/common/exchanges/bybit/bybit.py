import asyncio
import urllib.parse
import time
import logging
import hmac
from datetime import datetime
from decimal import Decimal

from aiohttp import ClientResponseError, ClientResponse

from balancebot.api.settings import settings
from balancebot.common.errors import ResponseError
from balancebot.common.exchanges.exchangeworker import ExchangeWorker, create_limit
from balancebot.common.dbmodels.balance import Balance
from typing import Dict


class BybitClient(ExchangeWorker):
    exchange = 'bybit'
    _ENDPOINT = 'https://api-testnet.bybit.com' if settings.testing else 'https://api.bybit.com'

    amount = float
    type = str

    _limits = [
        create_limit(interval_seconds=5, max_amount=5*70, default_weight=1),
        create_limit(interval_seconds=5, max_amount=5*50, default_weight=1),
        create_limit(interval_seconds=120, max_amount=120*50, default_weight=1),
        create_limit(interval_seconds=120, max_amount=120*20, default_weight=1)
    ]

    _response_error = 'ret_msg'
    _response_result = 'result'

    # https://bybit-exchange.github.io/docs/inverse/?console#t-balance
    async def _get_balance(self, time: datetime, upnl=True):

        balances, tickers = await asyncio.gather(
            self._get('/v2/private/wallet/balance'),
            self._get('/v2/public/tickers', sign=False, cache=True)
        )

        total_realized = total_unrealized = Decimal(0)
        extra_currencies: Dict[str, Decimal] = {}

        ticker_prices = {
            ticker['symbol']: ticker['last_price'] for ticker in tickers
        }
        err_msg = None
        for currency, balance in balances.items():
            realized = Decimal(balance['wallet_balance'])
            unrealized = Decimal(balances['equity'])
            price = Decimal(0)
            if currency == 'USDT':
                price = Decimal(1)
            elif unrealized > 0:
                price = ticker_prices.get(f'{currency}USD')
                extra_currencies[currency] = realized
                if not price:
                    logging.error(f'Bybit Bug: ticker prices do not contain info about {currency}:\n{ticker_prices}')
                    err_msg = 'This is a bug in the ByBit implementation.'
                    break
            total_realized += realized * Decimal(price)
            total_unrealized += unrealized * Decimal(price)

        return Balance(
            realized=total_realized,
            unrealized=total_unrealized,
            extra_currencies=extra_currencies,
            error=err_msg
        )

    # https://bybit-exchange.github.io/docs/inverse/?console#t-authentication
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        ts = int(time.time() * 1000)
        params['api_key'] = self._api_key
        params['timestamp'] = str(ts)
        query_string = urllib.parse.urlencode(params)
        sign = hmac.new(self._api_secret.encode('utf-8'), query_string.encode('utf-8'), 'sha256').hexdigest()
        params['sign'] = sign

    @classmethod
    def _check_for_error(cls, response_json: Dict, response: ClientResponse):
        if response_json['ret_code'] != 0:
            raise ResponseError(
                root_error=ClientResponseError(response.request_info, (response,)),
                human=response_json['ret_msg']
            )
