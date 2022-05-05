import json
import urllib.parse
import hmac
import logging
from datetime import datetime, timedelta
from typing import Union, List, Optional, Dict

import pytz
import ccxt.async_support as ccxt
from balancebot.common.dbmodels.execution import Execution
import balancebot.common.dbmodels.balance as balance
from balancebot.common.dbmodels.transfer import RawTransfer
from balancebot.common.exchanges.exchangeworker import ExchangeWorker
import time

from balancebot.common.exchanges.ftx.websocket import FtxWebsocketClient


class FtxClient(ExchangeWorker):
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
                                     session=self._session)
        self._ccxt = ccxt.ftx(
            config={
                'apiKey': self._api_key,
                'secret': self._api_secret,
                'session': self._session
            }
        )
        if self._subaccount:
            self._ccxt.headers = {
                'FTX-SUBACCOUNT': self._subaccount
            }

    async def connect(self):
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
                    type=data.get('type')
                )
            )

    # https://docs.ftx.com/#account
    async def _get_balance(self, time: datetime, upnl=True):
        response = await self._get('/api/account')
        amount = response['totalAccountValue'] if upnl else response['collateral']
        return balance.Balance(amount=amount, time=time)

    async def get_executions(self,
                             since: datetime = None):
        since = since or datetime.now(pytz.utc) - timedelta(days=180)
        # Offset by 1 millisecond because otherwise the same executions are refetched (ftx probably compares with >=)
        trades = await self._ccxt.fetch_my_trades(since=since.timestamp() * 1000 + 1)
        return [
            Execution(
                symbol=trade['symbol'],
                price=trade['price'],
                qty=trade['amount'],
                side=trade['side'],
                time=self._parse_ts(trade['timestamp'])
            )
            for trade in trades
        ]

    def _parse_date(self, date: datetime):
        return str(int(date.timestamp()))

    async def _convert_to_usd(self, amount: float, coin: str, date: datetime):
        if coin == "USD":
            return amount
        ts = int(date.timestamp())
        ticker = await self._get(f'/api/markets/{coin}/USD/candles', params={
            'resolution': 15,
            'start_time': str(ts),
            'end_time': str(ts + 15)
        })
        return amount * ticker[0]["open"]

    def _generate_transfers(self, transfers: List[Dict], withdrawal: bool):
        return [
            RawTransfer(
                -transfer['size'] if withdrawal else transfer['size'],
                datetime.fromisoformat(transfer['time']),
                transfer['coin']
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

    def _parse_ts(self, ts: Union[int, float]):
        return datetime.fromtimestamp(ts / 1000, pytz.utc)
