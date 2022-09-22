from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterator

from tradealpha.common.dbmodels import Execution, Balance
from tradealpha.common.dbmodels.transfer import RawTransfer
from tradealpha.common.enums import Side, ExecType
from tradealpha.common.exchanges.exchangeworker import ExchangeWorker
from tradealpha.common.models.miscincome import MiscIncome
from tradealpha.common.models.ohlc import OHLC


class MockExchange(ExchangeWorker):
    exchange = 'mock'
    EXEC_START = datetime(year=2022, month=1, day=1)

    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        pass

    async def _get_ohlc(self, market: str, since: datetime, to: datetime, resolution_s: int = None,
                        limit: int = None) -> list[OHLC]:
        data = [
            Decimal(10000),
            Decimal(12500),
            Decimal(15000),
            Decimal(17500),
            Decimal(20000),
            Decimal(22500),
            Decimal(25000),
            Decimal(22500)
        ]
        ohlc_data = [
            OHLC(
                open=val, high=val, low=val, close=val,
                volume=Decimal(0),
                time=self.EXEC_START + timedelta(hours=12 * index)
            )
            for index, val in enumerate(data)
        ]
        return [
            ohlc for ohlc in ohlc_data if since < ohlc.time < to
        ]

    async def _get_transfers(self,
                             since: datetime,
                             to: datetime = None) -> list[RawTransfer]:
        return [
            RawTransfer(
                amount=Decimal(1), time=self.EXEC_START - timedelta(days=1), coin='BTC', fee=Decimal(0)
            )
        ]

    async def _get_executions(self, since: datetime, init=False) -> tuple[Iterator[Execution], Iterator[MiscIncome]]:
        data = [
            dict(qty=1, price=10000, side=Side.SELL),
            dict(qty=1, price=10000, side=Side.BUY),
            dict(qty=1, price=15000, side=Side.BUY),
            dict(qty=1, price=20000, side=Side.SELL),
            dict(qty=2, price=25000, side=Side.SELL),
            dict(qty=1, price=20000, side=Side.BUY),
        ]
        return [
                   Execution(**attrs, time=self.EXEC_START + timedelta(days=index), type=ExecType.TRADE,
                             symbol='BTCUSDT')
                   for index, attrs in enumerate(data)
               ], []

    # https://binance-docs.github.io/apidocs/futures/en/#account-information-v2-user_data
    async def _get_balance(self, time: datetime, upnl=True):
        return Balance(
            realized=100,
            unrealized=100,
            time=datetime.now(pytz.utc)
        )
