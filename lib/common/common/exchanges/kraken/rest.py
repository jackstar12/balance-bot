import base64
import hashlib
import hmac
import time
import urllib.parse
from datetime import datetime

from aiohttp import ClientResponse

from common.exchanges.exchangeworker import ExchangeWorker, create_limit
from database import dbmodels


def get_kraken_signature(urlpath, data, secret):

    post_data = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + post_data).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()

    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    sig_digest = base64.b64encode(mac.digest())
    return sig_digest.decode()



class KrakenRestClient(ExchangeWorker):

    _ENDPOINT = "https://api.kraken.com"

    _response_result = "result"
    _response_error = "error"

    _limits = [
        create_limit(interval_seconds=3, max_amount=15, default_weight=1)
    ]

    async def _get_balance(self, time: datetime, upnl=True):
        response = await self.get('/0/private/TradeBalance')
        return dbmodels.BalanceDB(
            amount=response["e"] if upnl else response["tb"],
            time=time
        )

    async def _get_websocket_token(self):
        response = await self.get('/0/private/GetWebSocketsToken')
        return response["token"]

    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        nonce = int(time.monotonic())
        data['nonce'] = int(time.time())
        headers['API-Key'] = self._api_key
        headers['API-Sign'] = get_kraken_signature(path, data, self._api_secret)

    def _set_rate_limit_parameters(self, response: ClientResponse):
        pass