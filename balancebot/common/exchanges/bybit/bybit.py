import asyncio
import urllib.parse
import time
import logging
import hmac
from abc import ABC
from collections import namedtuple
from datetime import datetime
from decimal import Decimal
from enum import Enum

import aiohttp
import pytz
from aiohttp import ClientResponseError, ClientResponse

from balancebot.common import utils
from balancebot.common.config import TESTING
from balancebot.common.dbmodels.client import Client
from balancebot.common.dbmodels.execution import Execution
from balancebot.common.dbmodels.transfer import RawTransfer
from balancebot.common.enums import ExecType, Side
from balancebot.common.errors import ResponseError, InvalidClientError
from balancebot.common.exchanges.bybit.websocket import BybitWebsocketClient
from balancebot.common.exchanges.exchangeworker import ExchangeWorker, create_limit
from balancebot.common.dbmodels.balance import Balance
from typing import Dict, List, Union, Tuple, Optional, Type

from balancebot.common.models.async_websocket_manager import WebsocketManager
from balancebot.common.models.ohlc import OHLC


class Transfer(Enum):
    SUCCESS = "SUCCESS"
    PENDING = "PENDING"
    FAILED = "FAILED"


class Wallet(Enum):
    SPOT = 1
    DERIVATIVE = 2


class ContractType(Enum):
    INVERSE = 1
    LINEAR = 2


class Direction(Enum):
    PREV = "Prev"
    NEXT = "Next"


def tf_helper(tf: str, factor_seconds: int, ns: List[int]):
    return {
        factor_seconds * n: f'{int(n * factor_seconds / 60) if n < utils.DAY else tf}' for n in ns
    }


_interval_map = {
    **tf_helper('m', utils.MINUTE, [1, 3, 5, 15, 30]),
    **tf_helper('h', utils.HOUR, [1, 2, 4, 6, 8, 12]),
    **tf_helper('D', utils.DAY, [1]),
    **tf_helper('W', utils.WEEK, [1]),
    **tf_helper('M', utils.WEEK * 4, [1]),
}


class _BybitBaseClient(ExchangeWorker, ABC):
    supports_extended_data = True

    _ENDPOINT = 'https://api-testnet.bybit.com' if TESTING else 'https://api.bybit.com'
    _WS_ENDPOINT = 'wss://stream-testnet.bybit.com/realtime' if TESTING else 'wss://stream.bybit.com/realtime'

    _response_error = 'ret_msg'
    _response_result = 'result'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ws = BybitWebsocketClient(self._http,
                                        get_url=lambda: self._WS_ENDPOINT,
                                        on_message=self._on_message,
                                        on_connect=self._on_connect)
        # TODO: Fetch symbols https://bybit-exchange.github.io/docs/inverse/#t-querysymbol

    async def connect(self):
        await self._ws.connect()
        await self._ws.authenticate(self._api_key, self._api_secret)
        await self._ws.subscribe("execution")

    async def _on_connect(self, ws: BybitWebsocketClient):
        pass

    def _get_ws_url(self) -> str:
        return self._WS_ENDPOINT

    @classmethod
    def _parse_exec(cls, raw_exec: Dict):
        if raw_exec['exec_type'] == "Trade":
            symbol = raw_exec["symbol"]
            commission = Decimal(raw_exec["exec_fee"])
            price = Decimal(raw_exec["exec_price"])
            qty = Decimal(raw_exec["exec_qty"])

            # Unify Inverse and Linear
            contract_type = _get_contract_type(symbol)
            return Execution(
                symbol=symbol,
                price=price,
                qty=qty,
                commission=commission,
                time=cls._parse_ts(raw_exec["trade_time_ms"] / 1000),
                side=Side.BUY if raw_exec["side"] == "Buy" else Side.SELL,
                type=ExecType.TRADE,
                inverse=contract_type == ContractType.INVERSE,
                settle='USD' if contract_type == ContractType.LINEAR else symbol[:-3]
            )

    async def _on_message(self, ws: WebsocketManager, message: Dict):
        # https://bybit-exchange.github.io/docs/inverse/#t-websocketexecution
        if message["topic"] == "execution":
            for execution in (executions for executions in message["data"]):
                # {
                #     "symbol": "BTCUSD",
                #     "side": "Buy",
                #     "order_id": "xxxxxxxx-xxxx-xxxx-9a8f-4a973eb5c418",
                #     "exec_id": "xxxxxxxx-xxxx-xxxx-8b66-c3d2fcd352f6",
                #     "order_link_id": "",
                #     "price": "8300",
                #     "order_qty": 1,
                #     "exec_type": "Trade",
                #     "exec_qty": 1,
                #     "exec_fee": "0.00000009",
                #     "leaves_qty": 0,
                #     "is_maker": false,
                #     "trade_time": "2020-01-14T14:07:23.629Z"
                # }
                await self._on_execution(self._parse_exec(execution))

    # https://bybit-exchange.github.io/docs/inverse/?console#t-authentication
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        ts = int(time.time() * 1000)
        params['api_key'] = self._api_key
        params['timestamp'] = str(ts)
        query_string = urllib.parse.urlencode(sorted(params.items(), key=lambda kv: kv[0]))
        sign = hmac.new(self._api_secret.encode('utf-8'), query_string.encode('utf-8'), 'sha256').hexdigest()
        params['sign'] = sign

    @classmethod
    def _check_for_error(cls, response_json: Dict, response: ClientResponse):
        # https://bybit-exchange.github.io/docs/inverse/?console#t-errors
        code = response_json['ret_code']
        if code != 0:
            error: Type[ResponseError] = ResponseError
            if code in (10003, 10005, 33004):  # Invalid api key, Permission denied, Api Key Expired
                error = InvalidClientError

            raise error(
                root_error=ClientResponseError(response.request_info, (response,)),
                human=f'{response_json["ret_msg"]}, Code: {response_json["ret_code"]}'
            )

    async def _get_internal_transfers(self, since: datetime, wallet: Wallet) -> List[RawTransfer]:
        transfers = []

        res = await self._get('/asset/v1/private/transfer/list',
                              params={
                                  'start_time': self._parse_date(since),
                                  'status': Transfer.SUCCESS.value
                              })
        while res['list']:
            transfers.extend(res['list'])
            res = await self._get('/asset/v1/private/transfer/list',
                                  params={
                                      'start_time': self._parse_date(since),
                                      'status': Transfer.SUCCESS.value,
                                      'cursor': res['cursor'],
                                      'direction': Direction.NEXT.value
                                  })

        results = []

        # {
        #     "transfer_id": "selfTransfer_c5ae452d-43e8-47e6-aa7c-d2bab57c0958",
        #     "coin": "BTC",
        #     "amount": "1",
        #     "from_account_type": "CONTRACT",
        #     "to_account_type": "SPOT",
        #     "timestamp": "1629965054",
        #     "status": "SUCCESS"
        # }
        for transfer in transfers:
            amount = transfer["amount"]
            if (
                    (
                            transfer["from_account_type"] == "CONTRACT"
                            and
                            transfer["to_account_type"] == "SPOT"
                            and
                            wallet == Wallet.DERIVATIVE
                    ) or (
                    transfer["from_account_type"] == "SPOT"
                    and
                    transfer["to_account_type"] == "CONTRACT"
                    and
                    wallet == Wallet.SPOT
            )):
                # Withdrawals are signaled by negative amounts
                amount *= -1
            results.append(RawTransfer(
                amount=amount,
                time=self._parse_ts(transfer["timestamp"]),
                coin=transfer["coin"],
                fee=None
            ))

        return results

    def _parse_date(self, date: datetime):
        return int(date.timestamp() * 1000)


def _get_contract_type(contract: str):
    if contract.endswith('USDT'):
        return ContractType.LINEAR
    else:
        return ContractType.INVERSE


class _BybitDerivativesBaseClient(_BybitBaseClient):
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
        # TODO: Fetch symbols https://bybit-exchange.github.io/docs/inverse/#t-querysymbol

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> List[RawTransfer]:
        self._internal_transfers = (since, await self._get_internal_transfers(since, Wallet.DERIVATIVE))
        return self._internal_transfers[1]

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
            if page_init and page != page_init:
                params[page_param] = page
            response = await self._get(path, params=params, **kwargs)
            page = response.get(page_response, page + 1 if page_init == 1 else page)
            result = response.get(result_path)
            if result:
                results.extend(result)
        return results

    async def _get_internal_executions(self,
                                       contract_type: ContractType,
                              since: datetime,
                              init=False) -> List[Execution]:

        coins_to_fetch = set()

        if self._internal_transfers and self._internal_transfers[0] == since:
            for transfer in self._internal_transfers[1]:
                coins_to_fetch.add(transfer.coin)

        asset_records = await self._get('/v2/private/exchange-order/list',
                                        params={
                                            'limit': 50
                                        })
        # {
        #     "id": 31,
        #     "exchange_rate": 40.57202774,
        #     "from_coin": "BTC",
        #     "to_coin": "ETH",
        #     "to_amount": 4.05720277,
        #     "from_fee": 0.0005,
        #     "from_amount": 0.1,
        #     "created_at": "2020-06-15 03:32:52"
        # }
        for asset_record in asset_records:
            coins_to_fetch.add(asset_record["from_coin"])
            coins_to_fetch.add(asset_record["to_coin"])

        execs = []
        ts = self._parse_date(since) if since else None
        for coin in coins_to_fetch:
            if self._usd_like(coin):
                continue
            raw_execs = []
            params = {
                'symbol': f'{coin}USD',
            }
            if ts:
                params['start_time'] = ts
            if contract_type == ContractType.INVERSE:
                # https://bybit-exchange.github.io/docs/inverse/#t-usertraderecords
                raw_execs.extend(await self._get_paginated(
                    limit=200,
                    path='/v2/private/execution/list',
                    params=params.copy(),
                    page_param='page',
                    result_path="trade_list"

                ))
            elif contract_type == ContractType.LINEAR:
                params['symbol'] = f'{coin}USDT'
                raw_execs.extend(await self._get_paginated(
                    limit=100,
                    path='/private/linear/trade/execution/history-list',
                    params=params,
                    page_param='page_token',
                    page_response='page_token',
                    result_path="data",
                    page_init=None
                ))
            # https://bybit-exchange.github.io/docs/inverse_futures/#t-usertraderecords
            # raw_execs.extend(await self._get_paginated(
            #    limit=200,
            #    path='/futures/private/execution/list',
            #    params=params.copy(),
            #    page_param='page',
            #    result_path="trade_list"
            # ))
            # https://bybit-exchange.github.io/docs/linear/#t-userhistorytraderecords


            # {
            #     "order_id": "55bd3595-938d-4d7f-b1ab-7abd6a3ec1cb",
            #     "order_link_id": "",
            #     "side": "Sell",
            #     "symbol": "BTCUSDT",
            #     "exec_id": "730cc113-7f05-5f1e-82b5-432bba9dfeab",
            #     "price": 39391,
            #     "order_price": 39391,
            #     "order_qty": 0.009,
            #     "order_type": "Market",
            #     "fee_rate": 0.0006,
            #     "exec_price": 41469.5,
            #     "exec_type": "Trade",
            #     "exec_qty": 0.009,
            #     "exec_fee": 0.2239353,
            #     "exec_value": 373.2255,
            #     "leaves_qty": 0,
            #     "closed_size": 0.009,
            #     "last_liquidity_ind": "RemovedLiquidity",
            #     "trade_time": 1650444130,
            #     "trade_time_ms": 1650444130065
            # }

            for raw_exec in raw_execs:
                if raw_exec['exec_type'] == "Trade":
                    execs.append(self._parse_exec(raw_exec))

        return execs

    # https://bybit-exchange.github.io/docs/inverse/?console#t-balance
    async def _internal_get_balance(self, contract_type: ContractType, time: datetime, upnl=True):

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
            unrealized = Decimal(balance['equity'])
            price = 0
            if currency == 'USDT':
                if contract_type == ContractType.LINEAR:
                    price = Decimal(1)
            elif unrealized > 0 and contract_type == ContractType.INVERSE:
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

    async def _get_ohlc(self,
                        market: str,
                        since: datetime,
                        to: datetime,
                        resolution_s: int = None,
                        limit: int = None, ) -> List[OHLC]:

        limit = limit or 200

        if not resolution_s:
            limit, resolution_s = self._calc_resolution(
                limit,
                list(_interval_map.keys()),
                since,
                to
            )

        params = {
            'symbol': market,
            'interval': _interval_map[resolution_s],
            'from': int(since.timestamp())
        }
        if limit:
            params['limit'] = limit

        contract_type = _get_contract_type(market)
        # Different endpoints, but they both use the exact same repsonse
        if contract_type == ContractType.INVERSE:
            # https://bybit-exchange.github.io/docs/inverse/#t-markpricekline
            url = '/v2/public/mark-price-kline'
        elif contract_type == ContractType.LINEAR:
            # https://bybit-exchange.github.io/docs/linear/#t-markpricekline
            url = '/public/linear/mark-price-kline'
        else:
            raise

        data = await self._get(url, params=params)

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
                    volume=Decimal(0),
                    time=self._parse_ts(ohlc["start_at"])
                )
                for ohlc in data
            ]
        else:
            return []


class BybitInverseWorker(_BybitDerivativesBaseClient):
    exchange = 'bybit-inverse'

    _limits = [
        create_limit(interval_seconds=5, max_amount=5 * 70, default_weight=1),
        create_limit(interval_seconds=5, max_amount=5 * 50, default_weight=1),
        create_limit(interval_seconds=120, max_amount=120 * 50, default_weight=1),
        create_limit(interval_seconds=120, max_amount=120 * 20, default_weight=1)
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._internal_transfers: Optional[Tuple[datetime, List[RawTransfer]]] = None
        # TODO: Fetch symbols https://bybit-exchange.github.io/docs/inverse/#t-querysymbol

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> List[RawTransfer]:
        self._internal_transfers = (since, await self._get_internal_transfers(since, Wallet.DERIVATIVE))
        return self._internal_transfers[1]

    async def _get_executions(self,
                              since: datetime,
                              init=False) -> List[Execution]:
        return await self._get_internal_executions(ContractType.INVERSE, since, init)

    # https://bybit-exchange.github.io/docs/inverse/?console#t-balance
    async def _get_balance(self, time: datetime, upnl=True):
        return await self._internal_get_balance(ContractType.INVERSE, time, upnl)


class BybitLinearWorker(_BybitDerivativesBaseClient):
    exchange = 'bybit-linear'

    _limits = [
        create_limit(interval_seconds=5, max_amount=5 * 70, default_weight=1),
        create_limit(interval_seconds=5, max_amount=5 * 50, default_weight=1),
        create_limit(interval_seconds=120, max_amount=120 * 50, default_weight=1),
        create_limit(interval_seconds=120, max_amount=120 * 20, default_weight=1)
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._internal_transfers: Optional[Tuple[datetime, List[RawTransfer]]] = None
        # TODO: Fetch symbols https://bybit-exchange.github.io/docs/inverse/#t-querysymbol

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> List[RawTransfer]:
        self._internal_transfers = (since, await self._get_internal_transfers(since, Wallet.DERIVATIVE))
        return self._internal_transfers[1]

    async def _get_executions(self,
                              since: datetime,
                              init=False) -> List[Execution]:
        return await self._get_internal_executions(ContractType.LINEAR, since, init)

    # https://bybit-exchange.github.io/docs/inverse/?console#t-balance
    async def _get_balance(self, time: datetime, upnl=True):
        return await self._internal_get_balance(ContractType.LINEAR, time, upnl)



class BybitSpotClient(_BybitBaseClient):
    exchange = "bybit-spot"

    _limits = [
        # TODO: Tweak Rate Limiter (method based + continious limits)
        create_limit(interval_seconds=2 * 60, max_amount=2 * 50, default_weight=1)  # Some kind of type=Type.CONTINIOUS
    ]
