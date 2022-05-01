import asyncio
import urllib.parse
import hmac
import logging
from datetime import datetime, timedelta
from typing import Union

import pytz
from aiohttp import ClientResponse, ClientResponseError
from sqlalchemy import select
import ccxt.async_support as ccxt
from balancebot.api.database_async import db_first
from balancebot.api.dbmodels.execution import Execution
import balancebot.api.dbmodels.balance as balance
from balancebot.exchangeworker import ExchangeWorker
import time

from balancebot.common.exchanges.ftx.websocket import FtxWebsocketClient


class FtxClient(ExchangeWorker):
    exchange = 'ftx'
    _ENDPOINT = 'https://ftx.com'

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
        if response['success']:
            amount = response['result']['totalAccountValue']
        else:
            amount = 0
        return balance.Balance(amount=amount, error=response.get('error'), time=time)

    async def get_executions(self,
                             since: datetime):
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

    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs) -> None:
        ts = int(time.time() * 1000)

        signature_payload = f'{ts}{method}{path}{self._query_string(params)}'.encode()
        if data:
            signature_payload += data
        signature = hmac.new(self._api_secret.encode(), signature_payload, 'sha256').hexdigest()
        headers['FTX-KEY'] = self._api_key
        headers['FTX-SIGN'] = signature
        headers['FTX-TS'] = str(ts)
        if self._subaccount:
            headers['FTX-SUBACCOUNT'] = urllib.parse.quote(self._subaccount)

    async def _process_response(self, response: ClientResponse) -> dict:
        response_json = await response.json()
        try:
            response.raise_for_status()
        except ClientResponseError as e:
            logging.error(f'{e}\n{response_json}')

            error = ''
            if response.status == 400:
                error = f"400 Bad Request. This is probably a bug in the bot, please contact dev"
            elif response.status == 401:
                error = f"401 Unauthorized ({response_json['error']}).\nIs your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status == 403:
                error = f"403 Access Denied ({response_json['error']}).\nIs your api key valid? Did you specify the right subaccount? You might want to check your API access"
            elif response.status == 404:
                error = f"404 Not Found. This is probably a bug in the bot, please contact dev"
            elif response.status == 429:
                error = f"429 Rate Limit violated. Try again later"
            elif 500 <= response.status < 600:
                error = f"{response.status} ({response_json['error']}).\nProblem or Maintenance on {self.exchange} servers."

            response_json['error'] = error
            return response_json

        if response.status == 200:
            return response_json

    def _parse_ts(self, ts: Union[int, float]):
        return datetime.fromtimestamp(ts / 1000, pytz.utc)


