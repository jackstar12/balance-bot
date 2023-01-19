import asyncio
import hmac
import logging
import time
import urllib.parse
from abc import ABC
from collections import OrderedDict
from datetime import datetime, timedelta, date
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Tuple, Optional, Type, Callable
from sqlalchemy import select, func

from common.exchanges.bybit._base import ContractType, _BybitBaseClient, all_intervals, interval_map, Account
from core import json, map_list, utc_now, groupby
from aiohttp import ClientResponseError, ClientResponse

from core import utils, get_multiple, parse_isoformat
from database.dbasync import db_all
from database.dbmodels import Trade
from database.dbmodels.balance import Balance, Amount
from database.dbmodels.execution import Execution
from database.dbmodels.transfer import RawTransfer
from database.enums import ExecType, Side
from database.errors import ResponseError, InvalidClientError, RateLimitExceeded, WebsocketError
from common.exchanges.bybit.websocket import BybitWebsocketClient
from common.exchanges.exchangeworker import ExchangeWorker, create_limit
from database.models.async_websocket_manager import WebsocketManager
from database.models.market import Market
from database.models.ohlc import OHLC
from ccxt.async_support import bybit

logger = logging.getLogger()


def get_contract_type(contract: str):
    if contract.endswith('USDT'):
        return ContractType.LINEAR
    else:
        return ContractType.INVERSE


class BybitDerivativesWorker(_BybitBaseClient):
    # https://bybit-exchange.github.io/docs/derivativesV3/contract/#t-websocket
    _WS_ENDPOINT = 'wss://stream.bybit.com/contract/private/v3'
    _WS_SANDBOX_ENDPOINT = 'wss://stream-testnet.bybit.com/contract/private/v3'

    exchange = 'bybit-derivatives'

    _limits = [
        create_limit(interval_seconds=5, max_amount=5 * 70, default_weight=1),
        create_limit(interval_seconds=5, max_amount=5 * 50, default_weight=1),
        create_limit(interval_seconds=120, max_amount=120 * 50, default_weight=1),
        create_limit(interval_seconds=120, max_amount=120 * 20, default_weight=1)
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._internal_transfers: Optional[Tuple[datetime, List[RawTransfer]]] = None
        self._latest_balance = None
        # TODO: Fetch symbols https://bybit-exchange.github.io/docs/inverse/#t-querysymbol

    @classmethod
    def get_market(cls, raw: str) -> Optional[Market]:
        if raw.endswith('USDT'):
            return Market(
                base=raw[:-4],
                quote='USDT'
            )
        elif raw.endswith('USD'):
            return Market(
                base=raw[:-3],
                quote='USD'
            )

    @classmethod
    def set_weights(cls, weight: int, response: ClientResponse):
        used = response.headers.get('X-Bapi-Limit-Status')
        logger.info(f'Remaining: {used}')

    async def _get_paginated(self,
                             limit: int,
                             page_param: str,
                             path: str,
                             params: Dict,
                             page_response: str = None,
                             result_path: str = None,
                             page_init: int = 1,
                             **kwargs):
        page = page_init
        result = []
        results = []
        params['limit'] = limit
        while result and len(result) == limit or page == page_init:
            # https://bybit-exchange.github.io/docs/inverse/#t-usertraderecords
            if page:
                params[page_param] = page
            response = await self.get(path, params=params, **kwargs)
            page = response.get(page_response, page + 1 if page_init == 1 else page)
            result = response.get(result_path)
            if result:
                results.extend(result)
        return results

    async def get_instruments(self, contract: ContractType) -> list[dict]:
        resp = await self.get(
            '/derivatives/v3/public/instruments-info',
            params={'contract': contract.value},
            cache=True,
            sign=False
        )
        return resp['list']

    async def get_tickers(self, contract: ContractType) -> list[dict]:
        resp = await self.get(
            '/derivatives/v3/public/tickers',
            params={'contract': contract.value},
            cache=True,
            sign=False
        )
        return resp['list']

    async def _get_internal_executions_v3(self,
                                          contract_type: ContractType,
                                          since: datetime) -> List[Execution]:

        coins_to_fetch = set()

        since_ts = self._parse_date(since) if since else None

        pnlParams = {
            'limit': 50
        }

        if self._internal_transfers and self._internal_transfers[0] == since:
            for transfer in self._internal_transfers[1]:
                coins_to_fetch.add(transfer.coin)

        if since:
            pnlParams['startTime'] = self._parse_date(since.replace(hour=0, minute=0, second=0, microsecond=0))

        # https://bybit-exchange.github.io/docs/derivativesV3/contract/#t-dv_walletrecords
        asset_records = await self._get_paginated_v3(path='/contract/v3/private/account/wallet/fund-records',
                                                     params=pnlParams)

        pnlParams["coin"] = 'USDT'

        # https://bybit-exchange.github.io/docs/derivativesV3/contract/#t-dv_walletrecords
        usd_records = await self._get_paginated_v3(path='/contract/v3/private/account/wallet/fund-records',
                                                   params=pnlParams)

        balance = await self.get_balance()
        balance.client = self.client

        records_by_assets = groupby(asset_records, lambda a: a['coin'])
        required_execs = {}
        existing_symbols = {}

        execs = []

        # {
        #     "coin": "USDT",
        #     "type": "AccountTransfer",
        #     "amount": "500",
        #     "walletBalance": "2731.63599033",
        #     "execTime": "1658215763731"
        # }
        if records_by_assets:
            # sum(Decimal(record['amount']) for record in usd_records if record['type'] == 'RealisedPNL') + (Decimal("8293.8771") - Decimal(usd_records[0]['walletBalance']))
            # equal to sum of all closed p&ls

            for coin, records in records_by_assets.items():
                required_execs[coin] = sum(
                    Decimal(record["amount"])
                    for record in records
                    if record['type'] == 'RealisedPNL' and self.parse_ms_dt(record['execTime']) >= since
                )

                required_execs[coin] += balance.get_realized(coin) - Decimal(records[0]['walletBalance'])

            async with self.db_maker() as db:
                for row in await db.execute(
                        select(
                            Execution.symbol,
                            func.sum(Execution.size).label('total')
                        )
                                .where(Trade.client_id == self.client_id)
                                .join(Execution.trade)
                                .group_by(Execution.symbol),
                ):
                    existing_symbols[row.symbol] = row.total

        for coin in required_execs:

            symbols_to_fetch = []

            if coin == 'USDT':
                instruments = await self.get_tickers(ContractType.LINEAR)
                instruments.sort(
                    # When sorting the priority of fetching, the size of prior trades will be considered too
                    key=lambda i: Decimal(i['turnover24h']) + 100 * existing_symbols.get(i['symbol'], 0),
                    reverse=True
                )
                for instrument in instruments:
                    if not instrument['symbol'].endswith('PERP'):
                        symbols_to_fetch.append(instrument['symbol'])
            else:
                symbols_to_fetch.append(f'{coin}USD')

            params = {'limit': 200}
            if since_ts:
                params['startTime'] = since_ts
            for symbol in symbols_to_fetch:
                params['symbol'] = symbol
                pnlParams['symbol'] = symbol
                try:
                    raw_orders = await self._get_paginated_v3(path='/contract/v3/private/order/list',
                                                              valid=lambda r: int(r['createdTime']) > since_ts,
                                                              params=params)
                    if raw_orders:
                        # https://bybit-exchange.github.io/docs/derivativesV3/contract/#t-dv_closedprofitandloss
                        closed_pnl = await self._get_paginated_v3(path='/contract/v3/private/position/closed-pnl',
                                                                  params=pnlParams)

                    else:
                        continue
                except ResponseError:
                    self._logger.exception('Something went wrong with symbol: ' + symbol)
                    continue

                for raw_order in raw_orders:
                    parsed = self._parse_order_v3(raw_order)

                    if parsed:
                        execs.append(parsed)

                required_execs[coin] -= sum(Decimal(entry['closedPnl']) for entry in closed_pnl)

                if not required_execs[coin]:
                    break

        return list(execs)

    # https://bybit-exchange.github.io/docs/inverse/?console#t-balance
    async def _internal_get_balance(self, contract_type: ContractType, time: datetime, upnl=True):

        balances, tickers = await asyncio.gather(
            self.get('/v2/private/wallet/balance'),
            self.get('/v2/public/tickers', sign=False, cache=True)
        )

        total_realized = total_unrealized = Decimal(0)
        extra_currencies: list[Amount] = []

        ticker_prices = {
            ticker['symbol']: ticker['last_price'] for ticker in tickers
        }
        err_msg = None
        for currency, balance in balances.items():
            realized = Decimal(balance['wallet_balance'])
            unrealized = Decimal(balance['equity'])
            price = 0
            if currency == 'USDT':
                if contract_type == ContractType.LINEAR:
                    price = Decimal(1)
            elif unrealized > 0 and contract_type == ContractType.INVERSE:
                price = get_multiple(ticker_prices, f'{currency}USD', f'{currency}USDT')
                if not price:
                    logging.error(f'Bybit Bug: ticker prices do not contain info about {currency}:\n{ticker_prices}')
                    continue
            if contract_type != ContractType.LINEAR and realized:
                extra_currencies.append(
                    Amount(currency=currency, realized=realized, unrealized=unrealized)
                )
            total_realized += realized * Decimal(price)
            total_unrealized += unrealized * Decimal(price)

        return Balance(
            realized=total_realized,
            unrealized=total_unrealized,
            extra_currencies=extra_currencies,
            error=err_msg
        )

    async def _internal_get_balance_v3(self, contract_type: ContractType = None):

        params = {}
        if contract_type:
            params['category'] = contract_type.value

        balances, tickers = await asyncio.gather(
            self.get('/contract/v3/private/account/wallet/balance'),
            self.get('/derivatives/v3/public/tickers', params=params, sign=False, cache=True)
        )

        total_realized = total_unrealized = Decimal(0)
        extra_currencies: list[Amount] = []

        ticker_prices = {
            ticker['symbol']: Decimal(ticker['lastPrice']) for ticker in tickers['list']
        }
        err_msg = None
        for balance in balances["list"]:
            realized = Decimal(balance['walletBalance'])
            unrealized = Decimal(balance['equity']) - realized
            coin = balance["coin"]
            price = 0
            if coin == 'USDT':
                if contract_type == ContractType.LINEAR or not contract_type:
                    price = Decimal(1)
            elif realized and (contract_type == ContractType.INVERSE or not contract_type):
                price = get_multiple(ticker_prices, f'{coin}USD', f'{coin}USDT')
                if not price:
                    logging.error(f'Bybit Bug: ticker prices do not contain info about {coin}:\n{ticker_prices}')
                    continue

            if contract_type != ContractType.LINEAR and realized:
                extra_currencies.append(
                    Amount(currency=coin, realized=realized, unrealized=unrealized, rate=price)
                )
            total_realized += realized * price
            total_unrealized += unrealized * price

        return Balance(
            realized=total_realized,
            unrealized=total_unrealized,
            extra_currencies=extra_currencies,
            error=err_msg
        )

    async def _get_ohlc(self, symbol: str, since: datetime = None, to: datetime = None, resolution_s: int = None,
                        limit: int = None) -> List[OHLC]:

        limit = limit or 200

        if not resolution_s:
            limit, resolution_s = self._calc_resolution(
                limit,
                all_intervals,
                since,
                to
            )
        ts = int(since.timestamp())
        params = {
            'symbol': symbol,
            'interval': interval_map[resolution_s],
            'from': ts - (ts % resolution_s)
        }
        if limit:
            params['limit'] = limit

        contract_type = get_contract_type(symbol)
        # Different endpoints, but they both use the exact same repsonse
        if contract_type == ContractType.INVERSE:
            # https://bybit-exchange.github.io/docs/futuresV2/inverse/#t-markpricekline
            url = '/v2/public/mark-price-kline'
        elif contract_type == ContractType.LINEAR:
            # https://bybit-exchange.github.io/docs/futuresV2/linear/#t-markpricekline
            url = '/public/linear/mark-price-kline'
        else:
            raise

        data = await self.get(url, params=params, sign=False, cache=True)

        # "result": [{
        #     "id": 3866948,
        #     "symbol": "BTCUSDT",
        #     "period": "1",
        #     "start_at": 1577836800,
        #     "open": 7700,
        #     "high": 999999,
        #     "low": 0.5,
        #     "close": 6000
        # }

        if data:
            return [
                OHLC(
                    open=ohlc["open"],
                    high=ohlc["high"],
                    low=ohlc["low"],
                    close=ohlc["close"],
                    time=self.parse_ts(ohlc["start_at"])
                )
                for ohlc in data
            ]
        else:
            return []

    async def _get_transfers(self, since: datetime = None, to: datetime = None) -> List[RawTransfer]:
        self._internal_transfers = (since, await self._get_internal_transfers_v3(since, Account.DERIVATIVE))
        return self._internal_transfers[1]

    async def _get_executions(self,
                              since: datetime,
                              init=False):
        since = since or utc_now() - timedelta(days=365)
        return await self._get_internal_executions_v3(ContractType.LINEAR, since), []

    # https://bybit-exchange.github.io/docs/inverse/?console#t-balance
    async def _get_balance(self, time: datetime, upnl=True):
        # return await self._internal_get_balance_v3(ContractType.LINEAR)
        return await self._internal_get_balance_v3()


class BybitSpotClient(_BybitBaseClient):
    exchange = "bybit-spot"

    _limits = [
        # TODO: Tweak Rate Limiter (method based + continious limits)
        create_limit(interval_seconds=2 * 60, max_amount=2 * 50, default_weight=1)  # Some kind of type=Type.CONTINIOUS
    ]
