import hmac

import urllib.parse
import time
from datetime import datetime
from decimal import Decimal

from common.exchanges.exchangeworker import ExchangeWorker

import database.dbmodels.balance as db_balance


class BitmexWorker(ExchangeWorker):
    exchange = 'bitmex'
    _ENDPOINT = 'https://www.bitmex.com'

    _response_error = None
    _response_result = None

    @classmethod
    def _adjust_amount(self, amount: Decimal, symbol: str):
        if 'XBT' in symbol:
            # XBT amount is given in Sats (100 Million Sats = 1BTC)
            return amount * 10 ** -8
        # BITMEX WHY ???
        elif 'USDT' in symbol:
            return amount * 10 ** -6
        elif 'GWEI' in symbol or 'ETH' in symbol:
            return amount * 10 ** -9
        return amount

    # https://www.bitmex.com/api/explorer/#!/User/User_getMargin
    async def _get_balance(self, time: datetime, upnl=True):
        # Could do something like that for displaying a trade history
        # request = Request(
        #     'GET',
        #     self.ENDPOINT + 'execution/tradeHistory',
        #     params={
        #         'startTime': str(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
        #     }
        # )
        # res = self._request(request)
        response = await self.get(
            '/api/v1/user/margin',
            params={'currency': 'all'}
        )
        total_realized = total_unrealized = Decimal(0)
        extra_currencies = []

        for currency in response:
            symbol = currency['currency'].upper()
            unrealized_raw = currency['marginBalance']
            realized_raw = currency['walletBalance']
            price = 0
            if self._usd_like(symbol):
                price = 1
            elif unrealized_raw > 0:
                response_price = await self.get(
                    '/api/v1/trade',
                    params={
                        'symbol': symbol.upper(),
                        'count': 1,
                        'reverse': 'True'
                    }
                )
                if len(response_price) > 0:
                    price = response_price[0]['price']

            unrealized = self._adjust_amount(unrealized_raw, symbol)
            realized_amount = self._adjust_amount(realized_raw, symbol)

            extra_currencies.append(
                db_balance.Amount(currency=symbol, realized=realized_amount, unrealized=unrealized)
            )

            total_realized += realized_amount * price
            total_unrealized += unrealized * price

        return db_balance.Balance(realized=total_realized,
                                  unrealized=total_unrealized,
                                  extra_currencies=extra_currencies)

    # https://www.bitmex.com/app/apiKeysUsage
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        ts = int(time.time() * 1000)
        query_string = urllib.parse.urlencode(params, True)
        request_signature = f'{method}{path}{f"?{query_string}" if query_string else ""}{ts}'
        if data is not None:
            request_signature += data
        signature = hmac.new(self._api_secret.encode(), request_signature.encode(), 'sha256').hexdigest()
        headers['api-expires'] = str(ts)
        headers['api-key'] = self._api_key
        headers['api-signature'] = signature
