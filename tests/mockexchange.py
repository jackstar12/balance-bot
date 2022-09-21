from datetime import datetime
from decimal import Decimal

from tradealpha.common.enums import Side, ExecType
from tradealpha.common.exchanges.exchangeworker import ExchangeWorker


class MockExchange(ExchangeWorker):
    def _sign_request(self, method: str, path: str, headers=None, params=None, data=None, **kwargs):
        pass

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
                results.append(
                    Execution(
                        symbol=symbol,
                        realized_pnl=Decimal(income['income']),
                        time=self.parse_ms(income['time']),
                        type=ExecType.FUNDING if income_type == "FUNDING_FEE" else ExecType.LIQUIDATION
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
