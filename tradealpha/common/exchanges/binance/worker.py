from __future__ import annotations

import asyncio
import hmac
import json
import logging
import sys
import time
import urllib.parse
from abc import ABC
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import List, Iterator

import ccxt.async_support as ccxt
import pytz
from aiohttp import ClientResponse

import tradealpha.common.dbmodels.balance as balance
from tradealpha.common import utils
from tradealpha.common.dbmodels.execution import Execution
from tradealpha.common.dbmodels.transfer import RawTransfer
from tradealpha.common.enums import Side, ExecType
from tradealpha.common.exchanges.binance.futures_websocket_client import FuturesWebsocketClient
from tradealpha.common.exchanges.exchangeworker import ExchangeWorker, create_limit
from tradealpha.common.models.miscincome import MiscIncome
from tradealpha.common.models.ohlc import OHLC
from tradealpha.common.utils import utc_now

logger = logging.getLogger(__name__)


class Type(Enum):
    SPOT = 1
    USDM = 2
    COINM = 3


class _BinanceBaseClient(ExchangeWorker, ABC):
    supports_extended_data = True

    _ENDPOINT = 'https://api.binance.com'
    _SANDBOX_ENDPOINT = 'https://testnet.binance.vision'

    _response_error = 'msg'

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
                                      to: datetime = None) -> List[RawTransfer]:
        since = since or utc_now() - timedelta(days=180)
        if self.client.sandbox:
            return []
        response = await self.get(
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
            self._logger.error(f'Received invalid internal type: {type}')
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
                    date = self.parse_ms(row['timestamp'])
                    results.append(
                        RawTransfer(amount, date, row["asset"], fee=None)
                    )
        return results

    def _parse_datetime(self, date: datetime):
        # Offset by 1 in order to not include old entries on some endpoints
        return str(int(date.timestamp()) * 1000 + 1) if date else 0


def tf_helper(tf: str, factor_seconds: int, ns: List[int]):
    return {
        factor_seconds * n: f'{n}{tf}' for n in ns
    }


_interval_map = {
    **tf_helper('m', utils.MINUTE, [1, 3, 5, 15, 30]),
    **tf_helper('h', utils.HOUR, [1, 2, 4, 6, 8, 12]),
    **tf_helper('d', utils.DAY, [1, 3]),
    **tf_helper('w', utils.WEEK, [1])
}


class BinanceFutures(_BinanceBaseClient):
    _ENDPOINT = 'https://fapi.binance.com'
    _SANDBOX_ENDPOINT = 'https://testnet.binancefuture.com'
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

        limit = limit or 499
        resolution_s = resolution_s or 60

        limit, resolution_s = self._calc_resolution(limit,
                                                    resolutions_s=list(_interval_map.keys()),
                                                    since=since,
                                                    to=to)

        params = {
            'symbol': market,
            'interval': _interval_map.get(resolution_s),
            'startTime': self._parse_datetime(since),
            'endTime': self._parse_datetime(to),
            'limit': limit
        }

        data = await self.get(
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
                time=self.parse_ms(data[0]),
                open=Decimal(data[1]),
                high=Decimal(data[2]),
                low=Decimal(data[3]),
                close=Decimal(data[4]),
                volume=Decimal(0)
            )
            for data in data
        ]

    async def _fetch_execs(self, symbol: str, fromId: int, minTS: int):
        # https://binance-docs.github.io/apidocs/futures/en/#account-trade-list-user_data

        trades = await self.get('/fapi/v1/userTrades', params={
            'symbol': symbol,
            'fromId': fromId
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
        return (
            Execution(
                symbol=symbol,
                qty=Decimal(trade['qty']),
                price=Decimal(trade['price']),
                side=Side.BUY if trade['side'] == 'BUY' else Side.SELL,
                time=self.parse_ms(trade['time']),
                realized_pnl=Decimal(trade['realizedPnl']),
                commission=Decimal(trade['commission']),
                type=ExecType.TRADE
            )
            for trade in trades if trade['time'] >= minTS
        )

    async def _get_executions(self, since: datetime, init=False) -> tuple[Iterator[Execution], Iterator[MiscIncome]]:

        since_ts = self._parse_datetime(since or datetime.now(pytz.utc) - timedelta(days=180))
        # https://binance-docs.github.io/apidocs/futures/en/#get-income-history-user_data
        incomes = await self.get(
            '/fapi/v1/income',
            params={
                'startTime': since_ts,
                'limit': 1000
            }
        )
        symbols_done = set()
        current_commission = {}

        def get_safe(symbol: str, attr: str):
            income = current_commission.get(symbol)
            return income.get(attr) if income else None

        results = []
        misc = []

        for income in incomes:
            symbol = income.get('symbol')
            trade_id = income["tradeId"]
            income_type = income["incomeType"]
            if symbol not in symbols_done:

                if income_type == "COMMISSION":

                    if current_commission.get(symbol) or since:
                        symbols_done.add(symbol)

                        results.extend(
                            await self._fetch_execs(
                                symbol,
                                trade_id if since else get_safe(symbol, 'tradeId'),
                                income['time'] if since else get_safe(symbol, 'time')
                            )
                        )
                    current_commission[symbol] = income
                elif income_type == "REALIZED_PNL":
                    if get_safe(symbol, 'tradeId') == trade_id:
                        current_commission[symbol] = None
            if income_type == "INSURANCE_CLEAR" or income_type == "FUNDING_FEE":
                type = ExecType.FUNDING if income_type == "FUNDING_FEE" else ExecType.LIQUIDATION
                amount = Decimal(income['income'])
                results.append(
                    Execution(
                        symbol=symbol,
                        # realized_pnl=amount if type == ExecType.LIQUIDATION else 0,
                        # commission=amount if type == ExecType.FUNDING else 0,
                        realized_pnl=amount,
                        time=self.parse_ms(income['time']),
                        type=type
                    )
                )
            elif income_type not in ('COMMISSION', 'TRANSFER', 'REALIZED_PNL'):
                misc.append(
                    MiscIncome(
                        amount=Decimal(income['income']),
                        time=self.parse_ms(income['time'])
                    )
                )

        for symbol, income in current_commission.items():
            if symbol not in symbols_done:
                results.extend(
                    await self._fetch_execs(
                        symbol,
                        income['tradeId'],
                        income['time']
                    )
                )

        return results, misc

    # https://binance-docs.github.io/apidocs/futures/en/#account-information-v2-user_data
    async def _get_balance(self, time: datetime, upnl=True):
        response = await self.get('/fapi/v2/account')

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

    async def _connect(self):
        await self._ws.start()

    async def cleanup(self):
        await self._ws.stop()

    async def _on_message(self, ws, message):
        event = message['e']
        json.dump(message, fp=sys.stdout, indent=3)

        """
        {
          "e":"ORDER_TRADE_UPDATE",     // Event Type
          "E":1568879465651,            // Event Time
          "T":1568879465650,            // Transaction Time
          "o":{                             
            "s":"BTCUSDT",              // Symbol
            "c":"TEST",                 // Client Order Id
              // special client order id:
              // starts with "autoclose-": liquidation order
              // "adl_autoclose": ADL auto close order
              // "settlement_autoclose-": settlement order for delisting or delivery
            "S":"SELL",                 // Side
            "o":"TRAILING_STOP_MARKET", // Order Type
            "f":"GTC",                  // Time in Force
            "q":"0.001",                // Original Quantity
            "p":"0",                    // Original Price
            "ap":"0",                   // Average Price
            "sp":"7103.04",             // Stop Price. Please ignore with TRAILING_STOP_MARKET order
            "x":"NEW",                  // Execution Type
            "X":"NEW",                  // Order Status
            "i":8886774,                // Order Id
            "l":"0",                    // Order Last Filled Quantity
            "z":"0",                    // Order Filled Accumulated Quantity
            "L":"0",                    // Last Filled Price
            "N":"USDT",             // Commission Asset, will not push if no commission
            "n":"0",                // Commission, will not push if no commission
            "T":1568879465650,          // Order Trade Time
            "t":0,                      // Trade Id
            "b":"0",                    // Bids Notional
            "a":"9.91",                 // Ask Notional
            "m":false,                  // Is this trade the maker side?
            "R":false,                  // Is this reduce only
            "wt":"CONTRACT_PRICE",      // Stop Price Working Type
            "ot":"TRAILING_STOP_MARKET",    // Original Order Type
            "ps":"LONG",                        // Position Side
            "cp":false,                     // If Close-All, pushed with conditional order
            "AP":"7476.89",             // Activation Price, only puhed with TRAILING_STOP_MARKET order
            "cr":"5.0",                 // Callback Rate, only puhed with TRAILING_STOP_MARKET order
            "pP": false,              // ignore
            "si": 0,                  // ignore
            "ss": 0,                  // ignore
            "rp":"0"                            // Realized Profit of the trade
          }
        }        
        """
        if event == 'ORDER_TRADE_UPDATE':
            data = message.get('o')
            if data['X'] == 'FILLED':
                x = data['x']
                o = data['o']

                if o in ('MARKET', 'LIMIT'):
                    execType = ExecType.TRADE
                elif x == 'LIQUIDATION':
                    execType = ExecType.LIQUIDATION
                elif o == 'STOP':
                    execType = ExecType.STOP
                elif o == 'TAKE_PROFIT':
                    execType = ExecType.TP
                else:
                    return

                trade = Execution(
                    symbol=data['s'],
                    price=Decimal(data['ap']) or Decimal(data['p']),
                    qty=Decimal(data['q']),
                    side=data['S'],
                    time=self.parse_ms(message['E']),
                    type=execType,
                    realized_pnl=Decimal(data['rp']),
                    commission=Decimal(data['n'])
                )
                await self._on_execution(trade)

        # https://binance-docs.github.io/apidocs/futures/en/#event-balance-and-position-update
        if event == 'ACCOUNT_UPDATE':
            data = message.get['a']
            if data["m"] == "FUNDING_FEE":
                asset = data["B"][0]
                await self._on_execution(
                    Execution(
                        symbol=asset["a"],
                        time=self.parse_ms(message['E']),
                        type=ExecType.FUNDING,
                        commission=Decimal(asset['bc'])
                    )
                )

    @classmethod
    def set_weights(cls, weight: int, response: ClientResponse):
        limit = cls._limits[0]
        used = response.headers.get('X-MBX-USED-WEIGHT-1M')
        logger.info(f'Weight used: {used}')
        if used:
            limit.amount = limit.max_amount - int(used)
        else:
            limit.amount -= weight or limit.default_weight


class BinanceSpot(_BinanceBaseClient):
    _ENDPOINT = 'https://api.binance.com'
    _SANDBOX_ENDPOINT = 'https://testnet.binance.vision'
    exchange = 'binance-spot'
    supports_extended_data = False

    # https://binance-docs.github.io/apidocs/spot/en/#account-information-user_data
    async def _get_balance(self, time: datetime, upnl=True):

        results = await asyncio.gather(
            self.get('/api/v3/account'),
            self.get('/api/v3/ticker/price', sign=False, cache=True)
        )

        if isinstance(results[0], dict):
            response = results[0]
            tickers = results[1]
        else:
            response = results[1]
            tickers = results[0]

        total_balance = 0
        extra_currencies: list[balance.Amount] = []

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
                extra_currencies.append(
                    balance.Amount(currency=currency, realized=amount, unrealized=amount)
                )
                price = Decimal(ticker_prices.get(f'{currency}USDT', 0.0))
            total_balance += amount * price

        return balance.Balance(realized=total_balance, unrealized=total_balance, time=time)

    # async def _get_executions(self,
    #                           since: datetime,
    #                           init=False) -> tuple[List[Execution], List[MiscIncome]]:
    #     result = await self.get('/api/v3/myTrades', )

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> List[RawTransfer]:
        return await self._get_internal_transfers(Type.SPOT, since, to)
