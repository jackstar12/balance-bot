from __future__ import annotations

import itertools
from abc import ABC
from decimal import Decimal
from enum import Enum
from typing import NamedTuple, List, Optional, Union, Iterator

import asyncio
import hmac
import json
import logging
import sys
import time
import ccxt.async_support as ccxt
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict

import pytz
from aiohttp import ClientResponse

from balancebot.common.dbmodels.transfer import RawTransfer
from balancebot.common import utils
from balancebot.common.enums import Side, ExecType
from balancebot.common.exchanges.binance.futures_websocket_client import FuturesWebsocketClient
from balancebot.api.settings import settings
from balancebot.common.exchanges.exchangeworker import ExchangeWorker, create_limit
import balancebot.common.dbmodels.balance as balance
from balancebot.common.dbmodels.execution import Execution
from balancebot.common.models.ohlc import OHLC

logger = logging.getLogger(__name__)


class Type(Enum):
    SPOT = 1
    USDM = 2
    COINM = 3


class _BinanceBaseClient(ExchangeWorker, ABC):
    _ENDPOINT = 'https://testnet.binance.vision' if settings.testing else 'https://api.binance.com'

    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs) -> None:
        ts = int(time.time() * 1000)
        headers['X-MBX-APIKEY'] = self._api_key
        params['timestamp'] = ts
        query_string = urllib.parse.urlencode(params, True)
        signature = hmac.new(self._api_secret.encode(), query_string.encode(), 'sha256').hexdigest()
        params['signature'] = signature

    # https://binance-docs.github.io/apidocs/spot/en/#get-future-account-transaction-history-list-user_data
    async def _get_internal_transfers(self,
                                      type: Type,
                                      since: datetime,
                                      to: datetime = None) -> Optional[List[RawTransfer]]:
        if settings.testing:
            return
        response = await self._get(
            '/sapi/v1/futures/transfer',
            params={
                'startTime': self._parse_datetime(since)
            },
            endpoint=_BinanceBaseClient._ENDPOINT
        )

        """
        {
          "rows": [
            {
              "asset": "USDT",
              "tranId": 100000001,
              "amount": "40.84624400",
              "type": "1",  // one of 1( from spot to USDT-Ⓜ), 2( from USDT-Ⓜ to spot), 3( from spot to COIN-Ⓜ), and 4( from COIN-Ⓜ to spot)
              "timestamp": 1555056425000,
              "status": "CONFIRMED" //one of PENDING (pending to execution), CONFIRMED (successfully transfered), FAILED (execution failed, nothing happened to your account);
            }
          ],
          "total": 1
        }
        """
        # Tuples with one element look so weird
        if type == Type.USDM:
            deposit, withdraw = (1,), (2,)
        elif type == Type.COINM:
            deposit, withdraw = (3,), (4,)
        elif type == Type.SPOT:
            deposit, withdraw = (2, 4), (1, 3)
        else:
            logger.error(f'Received invalid internal type: {type}')
            return

        results = []
        if 'rows' in response:
            for row in response['rows']:
                if row["status"] == "CONFIRMED":
                    if row["type"] in deposit:
                        amount = Decimal(row['amount'])
                    elif row["type"] in withdraw:
                        amount = -Decimal(row['amount'])
                    else:
                        continue
                    date = self._parse_ts(row['timestamp'])
                    results.append(
                        RawTransfer(amount, date, row["asset"])
                    )
        return results

    def _parse_ts(self, ts: Union[int, float, str]):
        return datetime.fromtimestamp(int(ts) / 1000, pytz.utc)

    def _parse_datetime(self, date: datetime):
        # Offset by 1 in order to not include old entries on some endpoints
        return str(int(date.timestamp()) * 1000 + 1)


def tf_helper(tf: str, factor_seconds: int, ns: List[int]):
    return {
        factor_seconds * n: f'{n}{tf}' for n in ns
    }


_interval_map = {
    **tf_helper('m', utils.MINUTE, [1, 3, 5, 15, 30]),
    **tf_helper('h', utils.HOUR, [1, 2, 4, 6, 8, 12]),
    **tf_helper('d', utils.DAY, [1, 3]),
    **tf_helper('w', utils.WEEK, [1]),
    None: '1m'
}


class BinanceFutures(_BinanceBaseClient):
    _ENDPOINT = 'https://testnet.binancefuture.com' if settings.testing else 'https://fapi.binance.com'
    exchange = 'binance-futures'

    _limits = [
        create_limit(interval_seconds=60, max_amount=1200, default_weight=20)
    ]

    _response_error = 'msg'
    _response_result = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._ws = FuturesWebsocketClient(self, session=self._http, on_message=self._on_message)
        self._ccxt = ccxt.binanceusdm({
            'apiKey': self._api_key,
            'secret': self._api_secret
        })
        self._ccxt.set_sandbox_mode(True)

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> List[RawTransfer]:
        return await self._get_internal_transfers(Type.USDM, since, to)

    async def _get_ohlc(self,
                        market: str,
                        since: datetime,
                        to: datetime,
                        resolution_s: int = None,
                        limit: int = None) -> List[OHLC]:
        # https://binance-docs.github.io/apidocs/futures/en/#mark-price-kline-candlestick-data
        params = {
            'symbol': market,
            'interval': _interval_map.get(resolution_s),
            'startTime': self._parse_datetime(since),
            'endTime': self._parse_datetime(to),
        }
        if limit:
            params['limit'] = limit
        data = await self._get(
            '/fapi/v1/markPriceKlines',
            params={
                'symbol': market,
                'interval': _interval_map.get(resolution_s),
                'startTime': self._parse_datetime(since),
                'endTime': self._parse_datetime(to)
            }
        )
        return [
            OHLC(
                time=self._parse_ts(data[0]),
                open=Decimal(data[1]),
                high=Decimal(data[2]),
                low=Decimal(data[3]),
                close=Decimal(data[4]),
                volume=Decimal(0)
            )
            for data in data
        ]

    async def _get_executions(self, since: datetime, init=False) -> Iterator[Execution]:

        since_ts = self._parse_datetime(since or datetime.now(pytz.utc) - timedelta(days=180))
        # https://binance-docs.github.io/apidocs/futures/en/#get-income-history-user_data
        incomes = await self._get(
            '/fapi/v1/income',
            params={
                'startTime': since_ts,
                'limit': 1000
            }
        )
        symbols_done = set()
        results = []
        current_commision_trade_id = {}

        for income in incomes:
            symbol = income.get('symbol')
            if symbol not in symbols_done:
                trade_id = income["tradeId"]
                income_type = income["incomeType"]

                if income_type == "COMMISSION":
                    if (current_commision_trade_id.get(symbol)) or since:
                        # https://binance-docs.github.io/apidocs/futures/en/#account-trade-list-user_data
                        symbols_done.add(symbol)
                        trades = await self._get('/fapi/v1/userTrades', params={
                            'symbol': symbol,
                            'fromId': trade_id if since is not None else current_commision_trade_id[symbol]
                        })
                        """
                        [
                          {
                            "buyer": false,
                            "commission": "-0.07819010",
                            "commissionAsset": "USDT",
                            "id": 698759,
                            "maker": false,
                            "orderId": 25851813,
                            "price": "7819.01",
                            "qty": "0.002",
                            "quoteQty": "15.63802",
                            "realizedPnl": "-0.91539999",
                            "side": "SELL",
                            "positionSide": "SHORT",
                            "symbol": "BTCUSDT",
                            "time": 1569514978020
                          }
                        ]
                        """
                        # -1790.6910700000062
                        # -1695.67399983
                        all = sum(Decimal(trade['realizedPnl']) - Decimal(trade["commission"]) for trade in trades)
                        results.extend(
                            (
                                Execution(
                                    symbol=symbol,
                                    qty=Decimal(trade['qty']),
                                    price=Decimal(trade['price']),
                                    side=Side.BUY if trade['side'] == 'BUY' else Side.SELL,
                                    time=self._parse_ts(trade['time']),
                                    commission=Decimal(trade['commission']),
                                    type=ExecType.TRADE
                                )
                                for trade in trades
                            )
                        )
                    current_commision_trade_id[symbol] = trade_id
                elif income_type == "REALIZED_PNL" and current_commision_trade_id.get(symbol) == trade_id:
                    current_commision_trade_id[symbol] = None

        return results

    # https://binance-docs.github.io/apidocs/futures/en/#account-information-v2-user_data
    async def _get_balance(self, time: datetime, upnl=True):
        response = await self._get('/fapi/v2/account')

        usd_assets = [
            asset for asset in response["assets"] if asset["asset"] in ("USDT", "BUSD")
        ]

        return balance.Balance(
            realized=sum(
                Decimal(asset['walletBalance'])
                for asset in usd_assets
            ),
            unrealized=sum(
                Decimal(asset['marginBalance'])
                for asset in usd_assets
            ),
            time=time if time else datetime.now(pytz.utc)
        )

    async def connect(self):
        await self._ws.start()

    async def _on_message(self, ws, message):
        message = json.loads(message)
        event = message['e']
        data = message.get('o')
        json.dump(message, fp=sys.stdout, indent=3)
        if event == 'ORDER_TRADE_UPDATE':
            if data['X'] == 'FILLED':
                trade = Execution(
                    symbol=data['s'],
                    price=Decimal(data['ap']) or Decimal(data['p']),
                    qty=Decimal(data['q']),
                    side=data['S'],
                    time=self._parse_ts(message['E']),
                )
                await utils.call_unknown_function(self._on_execution, trade)

    @classmethod
    def set_weights(cls, weight: int, response: ClientResponse):
        limit = cls._limits[0]
        used = response.headers.get('X-MBX-USED-WEIGHT-1M')
        if used:
            limit.amount = limit.max_amount - int(used)
        else:
            limit.amount -= weight or limit.default_weight


class BinanceSpot(_BinanceBaseClient):
    _ENDPOINT = 'https://testnet.binance.vision' if settings.testing else 'https://api.binance.com'
    exchange = 'binance-spot'

    # https://binance-docs.github.io/apidocs/spot/en/#account-information-user_data
    async def _get_balance(self, time: datetime, upnl=True):

        results = await asyncio.gather(
            self._get('/api/v3/account'),
            self._get('/api/v3/ticker/price', sign=False, cache=True)
        )

        if isinstance(results[0], dict):
            response = results[0]
            tickers = results[1]
        else:
            response = results[1]
            tickers = results[0]

        total_balance = 0
        extra_currencies: Dict[str, float] = {}

        ticker_prices = {
            ticker['symbol']: ticker['price'] for ticker in tickers
        }
        data = response['balances']
        for cur_balance in data:
            currency = cur_balance['asset']
            amount = Decimal(cur_balance['free']) + Decimal(cur_balance['locked'])
            price = 0
            if currency == 'USDT':
                price = 1
            elif amount > 0 and currency != 'LDUSDT' and currency != 'LDSRM':
                price = Decimal(ticker_prices.get(f'{currency}USDT', 0.0))
            total_balance += amount * price

        return balance.Balance(amount=total_balance, time=time)

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> List[RawTransfer]:
        return await self._get_internal_transfers(Type.SPOT, since, to)
