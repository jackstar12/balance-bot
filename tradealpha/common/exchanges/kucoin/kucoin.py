import base64
from abc import ABC

import pytz
import hmac
from datetime import datetime

import time
from decimal import Decimal
from typing import List, Literal

from tradealpha.common import utils
from tradealpha.common.dbmodels.execution import Execution
from tradealpha.common.dbmodels.transfer import RawTransfer
from tradealpha.common.exchanges.exchangeworker import ExchangeWorker
from tradealpha.common.dbmodels.balance import Balance
from tradealpha.common.models.ohlc import OHLC
from tradealpha.common.config import TESTING
from tradealpha.common.models.ticker import Ticker


class _KuCoinClient(ExchangeWorker, ABC):
    required_extra_args = [
        'passphrase'
    ]

    _response_error = None
    _response_result = 'data'

    # https://docs.kucoin.com/#authentication
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        ts = int(time.time() * 1000)
        signature_payload = f'{ts}{method}{path}{self._query_string(params)}'
        if data is not None:
            signature_payload += data
        signature = base64.b64encode(
            hmac.new(self._api_secret.encode('utf-8'), signature_payload.encode('utf-8'), 'sha256').digest()
        ).decode()
        passphrase = base64.b64encode(
            hmac.new(self._api_secret.encode('utf-8'), self._extra_kwargs['passphrase'].encode('utf-8'),
                     'sha256').digest()
        ).decode()
        headers['KC-API-KEY'] = self._api_key
        headers['KC-API-TIMESTAMP'] = str(ts)
        headers['KC-API-SIGN'] = signature
        headers['KC-API-PASSPHRASE'] = passphrase
        headers['KC-API-KEY-VERSION'] = '2'


class KuCoinFuturesWorker(_KuCoinClient):
    exchange = 'kucoin'
    _ENDPOINT = 'https://api-sandbox-futures.kucoin.com' if TESTING else 'https://api-futures.kucoin.com'

    required_extra_args = [
        'passphrase'
    ]

    _response_error = None
    _response_result = 'data'

    async def _get_url(self):
        resp = await self._post('/api/v1/bullet-private')
        server = resp["instanceServers"][0]
        return server["endpoint"] + f'?token={resp["token"]}'


    async def connect(self):
        self._ws = None



    # https://docs.kucoin.com/futures/#get-real-time-ticker
    async def _get_ticker(self,
                          symbol: str):
        resp = await self._get('/api/v1/ticker',
                        params={
                            'symbol': symbol
                        })
        return Ticker(
            symbol,
            self.exchange,

        )

    async def _fetch_transaction_history(self,
                                         since: datetime = None,
                                         to: datetime = None,
                                         transaction_type: Literal[
                                             'RealizedPNL',
                                             'Deposit',
                                             'Withdraw',
                                             'Transferin',
                                             'Transferout'
                                         ] = None):
        params = {}
        if since:
            params['startAt'] = self._date_as_ms(since)
        if to:
            params['endAt'] = self._date_as_ms(to)
        if transaction_type:
            params['type'] = transaction_type

        # https://docs.kucoin.com/futures/#get-transaction-history
        return await self._get('/api/v1/transaction-history',
                               params=params)

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> List[RawTransfer]:
        transactions = await self._fetch_transaction_history(since, to)
        results = []
        for transfer in transactions["dataList"]:
            # {
            #     "time": 1557997200000,
            #     "type": "RealisedPNL",
            #     "amount": -0.000017105,
            #     "fee": 0,
            #     "accountEquity": 8060.7899305281,
            #     "status": "Completed", // Status.Status.Funding period that has been settled.
            #     "remark": "XBTUSDM",
            #     "offset": 1,
            #     "currency": "XBT"
            # }
            if transfer["status"] == "Completed":
                if transfer["type"] in ("Withdraw", "TransferOut", "Deposit", "TransferIn"):
                    date = datetime.fromtimestamp(transfer["time"], pytz.utc)
                    amount = await self._convert_to_usd(Decimal(transfer["amount"]),
                                                        transfer["currency"],
                                                        date)

                    if transfer["type"] in ("Withdraw", "TransferOut"):
                        amount *= -1

                    results.append(
                        RawTransfer(
                            amount=amount,
                            time=datetime.fromtimestamp(transfer["time"], pytz.utc),
                            coin=transfer["currency"],
                            fee=transfer["fee"]
                        )
                    )

        return results

    async def _get_ohlc(self, market: str,
                        since: datetime,
                        to: datetime,
                        resolution_s: int = None,
                        limit: int = None) -> List[OHLC]:
        # https://docs.kucoin.com/futures/#k-chart
        limit = limit or 200  # Maximum amount of data points
        _, res = self._calc_resolution(limit,
                                       resolutions_s=[
                                           m * 60
                                           for m in (
                                               1, 5, 15, 30, 60,
                                               120, 240, 480,
                                               720, 1440, 10080
                                           )
                                       ],
                                       since=since,
                                       to=to)

        params = {
            'granularity': res
        }
        if since:
            params['from'] = self._date_as_ms(since)
        if to:
            params['to'] = self._date_as_ms(to)

        ohlc_data = await self._get('/api/v1/kline/query',
                                    params=params)

        return [
            OHLC(
               self._parse_ts(ohlc[0]),
               *ohlc[1:]
            )
            for ohlc in ohlc_data
        ]

    async def _get_executions(self,
                              since: datetime,
                              init=False) -> List[Execution]:
        transactions = await self._fetch_transaction_history(since, transaction_type='RealizedPNL')

        # https://docs.kucoin.com/futures/#get-fills
        fills = await self._get('/api/v1/fills')

        [
            Execution(
                **utils.mask_dict(fills, "symbol", "price", Decimal)
            )
            for fill in fills
        ]

        for pnl in transactions["dataList"]:
            # {
            #     "time": 1557997200000,
            #     "type": "RealisedPNL",
            #     "amount": -0.000017105,
            #     "fee": 0,
            #     "accountEquity": 8060.7899305281,
            #     "status": "Completed", // Status.Status.Funding period that has been settled.
            #     "remark": "XBTUSDM",
            #     "offset": 1,
            #     "currency": "XBT"
            # }
            date = datetime.fromtimestamp(pnl["time"], pytz.utc)
            amount = await self._convert_to_usd(Decimal(pnl["amount"]),
                                                pnl["currency"],
                                                date)

            if pnl["type"] in ("Withdraw", "TransferOut"):
                amount *= -1

            results.append(
                RawTransfer(
                    amount=amount,
                    time=datetime.fromtimestamp(pnl["time"], pytz.utc),
                    coin=pnl["currency"],
                    fee=pnl["fee"]
                )
            )

        pass
        # TODO: find more than 1 week?

