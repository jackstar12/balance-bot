from datetime import datetime

from tradealpha.common.exchanges.exchangeworker import ExchangeWorker


class MockExchange(ExchangeWorker):
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        pass

    async def _get_balance(self, time: datetime, upnl=True):
        pass
