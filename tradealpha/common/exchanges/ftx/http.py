import json
import urllib.parse
import hmac
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Union, List, Optional, Dict, Iterator

import pytz
import ccxt.async_support as ccxt
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.common.dbmodels.execution import Execution
import tradealpha.common.dbmodels.balance as balance
from tradealpha.common.dbmodels.transfer import RawTransfer
from tradealpha.common.enums import Side, ExecType
from tradealpha.common.exchanges.exchangeworker import ExchangeWorker
import time

from tradealpha.common.exchanges.ftx.websocket import FtxWebsocketClient
from tradealpha.common.models.ohlc import OHLC


class FtxWorker(ExchangeWorker):
    supports_extended_data = True
    exchange = 'ftx'
    _ENDPOINT = 'https://ftx.com'

    _response_error = 'error'
    _response_result = 'result'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ws = FtxWebsocketClient(api_key=self._api_key,
                                     api_secret=self._api_secret,
                                     subaccount=self._subaccount,
                                     on_message_callback=self._on_message,
                                     session=self._http)
        self._ccxt = ccxt.ftx(
            config={
                'apiKey': self._api_key,
                'secret': self._api_secret,
                'session': self._http
            }
        )
        if self._subaccount:
            self._ccxt.headers = {
                'FTX-SUBACCOUNT': self._subaccount
            }

    async def _connect(self):
        await self.ws.connect()
        await self.ws.get_fills()

    async def _on_message(self, message):
        logging.info(f'FTX MESSAGE! {message}')
        if message['channel'] == 'fills':
            data = message['data']
            await self._on_execution(
                execution=Execution(
                    symbol=data['market'],
                    side=data['side'].upper(),
                    price=float(data['price']),
                    qty=float(data['size']),
                    time=datetime.now(pytz.utc),
                    type=ExecType.TRADE
                )
            )

    # https://docs.ftx.com/#account
    async def _get_balance(self, time: datetime, upnl=True):
        response = await self._get('/api/wallet/balances')
        return balance.Balance(
            realized=sum(coin['usdValue'] for coin in response),
            unrealized=sum(coin['usdValue'] for coin in response),
            time=time
        )
        response = await self._get('/api/account')

        return balance.Balance(
            realized=response['collateral'],
            unrealized=response['totalAccountValue'],
            time=time
        )

    async def _get_executions(self, since: datetime, init=False):
        since = since or datetime.now(pytz.utc) - timedelta(days=365)
        # Offset by 1 millisecond because otherwise the same executions are refetched (ftx probably compares with >=)
        trades = await self._get('/api/fills', params={
            'start_time': self._parse_date(since),
            'end_time': str(time.time()),
            'order': 'asc'
        })
        return (
            [
                Execution(
                    symbol=trade['market'] if trade['market'] else f'{trade["baseCurrency"]}/{trade["quoteCurrency"]}',
                    price=trade['price'],
                    qty=trade['size'],
                    side=Side.BUY if trade['side'] == 'buy' else Side.SELL,
                    time=datetime.fromisoformat(trade["time"]),
                    commission=trade["fee"],
                    type=ExecType.TRADE
                )
                for trade in trades
            ],
            []
        )

    def _parse_date(self, date: datetime):
        return str(int(date.timestamp()))

    async def _convert_to_usd(self, amount: Decimal, coin: str, date: datetime):
        if self._usd_like(coin):
            return amount
        ticker = await self._get_ohlc(f'{coin}/USD', since=date, limit=1)
        return amount * (ticker[0].open + ticker[0].close) / 2

    async def _get_ohlc(self, market: str, since: datetime = None, to: datetime = None, resolution_s: int = None,
                        limit: int = None) -> List[OHLC]:

        resolution_s = resolution_s or 15
        params = {'resolution': resolution_s}

        if since:
            params['start_time'] = int(since.timestamp())
            if not to:
                params['end_time'] = params['start_time'] + resolution_s * limit
        if to:
            params['end_time'] = int(to.timestamp())
            if not since:
                params['start_time'] = params['end_time'] - resolution_s * limit

        res = await self._get(f'/api/markets/{market}/candles', params=params)

        return [
            OHLC(
                open=candle['open'],
                high=candle['high'],
                low=candle['low'],
                close=candle['close'],
                volume=candle['volume'],
                time=datetime.fromisoformat(candle['startTime'])
            )
            for candle in res
        ]

    @classmethod
    def _generate_transfers(cls, transfers: List[Dict], withdrawal: bool):
        return [
            RawTransfer(
                -transfer['size'] if withdrawal else transfer['size'],
                datetime.fromisoformat(transfer['time']),
                transfer['coin'],
                fee=None
            )
            for transfer in transfers
        ]

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> Optional[List[RawTransfer]]:
        withdrawals = await self._get('/api/wallet/withdrawals', params={'start_time': self._parse_date(since)})
        deposits = await self._get('/api/wallet/deposits', params={'start_time': self._parse_date(since)})

        withdrawals_data = self._generate_transfers(withdrawals, withdrawal=True)
        deposits_data = self._generate_transfers(deposits, withdrawal=False)

        return withdrawals_data + deposits_data

    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs) -> None:
        ts = int(time.time() * 1000)

        signature_payload = f'{ts}{method}{path}{self._query_string(params)}'
        if data:
            signature_payload += json.dumps(data)
        signature = hmac.new(self._api_secret.encode('utf-8'), signature_payload.encode('utf-8'), 'sha256').hexdigest()
        headers['FTX-KEY'] = self._api_key
        headers['FTX-SIGN'] = signature
        headers['FTX-TS'] = str(ts)
        if self._subaccount:
            headers['FTX-SUBACCOUNT'] = urllib.parse.quote(self._subaccount)
