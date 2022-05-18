import base64

import hmac
from datetime import datetime

import time
from balancebot.common.exchanges.exchangeworker import ExchangeWorker
from balancebot.common.dbmodels.balance import Balance


class KuCoinClient(ExchangeWorker):
    exchange = 'kucoin'
    _ENDPOINT = 'https://api-futures.kucoin.com'

    required_extra_args = [
        'passphrase'
    ]

    _response_error = None
    _response_result = 'data'

    # https://docs.kucoin.com/futures/#get-account-overview
    async def _get_balance(self, time: datetime, upnl=True):
        data = await self._get(
            '/api/v1/account-overview',
            params={'currency': 'USDT'}
        )
        return Balance(unrealized=data['accountEquity'], realized=data['marginBalance'], time=time)

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
            hmac.new(self._api_secret.encode('utf-8'), self._extra_kwargs['passphrase'].encode('utf-8'), 'sha256').digest()
        ).decode()
        headers['KC-API-KEY'] = self._api_key
        headers['KC-API-TIMESTAMP'] = str(ts)
        headers['KC-API-SIGN'] = signature
        headers['KC-API-PASSPHRASE'] = passphrase
        headers['KC-API-KEY-VERSION'] = '2'
