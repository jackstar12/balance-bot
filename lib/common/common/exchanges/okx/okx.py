from decimal import Decimal

import database.dbmodels.balance as balance
import ccxt.async_support as ccxt
from datetime import datetime
from common.exchanges.exchangeworker import ExchangeWorker


class OkxWorker(ExchangeWorker):

    ENDPOINT = 'https://www.okx.com'

    exchange = 'okx'
    required_extra_args = ['passphrase']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ccxt_client = ccxt.okex({
            'apiKey': self._api_key,
            'secret': self._api_secret,
            'password': self._extra_kwargs['passphrase'],
            'session': self._http
        })

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

        error = None

        try:
            tickers = await self.ccxt_client.fetch_tickers()
            total_balance = await self.ccxt_client.fetch_balance()
        except ccxt.errors.AuthenticationError:
            error = 'Unauthorized. Is your api key valid? Did you specify the right subaccount? You might want to check your API access.'
        except ccxt.errors.ExchangeError:
            error = 'This is a problem with the OKEX servers, try again later.'
        except ccxt.errors.BaseError as e:
            error = str(e)

        total = 0
        if error is None:
            for currency, amount in total_balance['total'].items():
                price = 0
                if currency == 'USDT':
                    price = 1
                elif amount > 0:
                    price = tickers.get(f'{currency}/USDT')['last']
                total += amount * price
        return balance.Balance(realized=Decimal(total), unrealized=Decimal(total), error=error)

    async def cleanup(self):
        await self.ccxt_client.close()

    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        pass
