import hmac
import hmac
import itertools
import time
import urllib.parse
from abc import ABC
from collections import OrderedDict
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Type, Callable

from aiohttp import ClientResponseError, ClientResponse

from common.exchanges.bybit.websocket import BybitWebsocketClient
from common.exchanges.exchangeworker import ExchangeWorker
from core import map_list
from core import utils, get_multiple, parse_isoformat
from database.dbmodels.execution import Execution
from database.dbmodels.transfer import RawTransfer
from database.enums import ExecType, Side
from database.errors import ResponseError, InvalidClientError, RateLimitExceeded, WebsocketError
from database.models.async_websocket_manager import WebsocketManager
from database.models.market import Market


class Transfer(Enum):
    SUCCESS = "SUCCESS"
    PENDING = "PENDING"
    FAILED = "FAILED"


class Account(Enum):
    SPOT = "SPOT"
    DERIVATIVE = "DERIVATIVE"
    UNIFIED = "UNIFIED"
    INVESTMENT = "INVESTMENT"
    OPTION = "OPTION"


class ContractType(Enum):
    INVERSE = "inverse"
    LINEAR = "linear"


class Direction(Enum):
    PREV = "Prev"
    NEXT = "Next"


def tf_helper(tf: str, factor_seconds: int, ns: list[int]):
    return {
        factor_seconds * n: f'{int(n * factor_seconds / 60) if n < utils.DAY else tf}' for n in ns
    }


interval_map = {
    **tf_helper('m', utils.MINUTE, [1, 3, 5, 15, 30]),
    **tf_helper('h', utils.HOUR, [1, 2, 4, 6, 8, 12]),
    **tf_helper('D', utils.DAY, [1]),
    **tf_helper('W', utils.WEEK, [1]),
    **tf_helper('M', utils.WEEK * 4, [1]),
}

all_intervals = list(interval_map.keys())


class _BybitBaseClient(ExchangeWorker, ABC):
    supports_extended_data = True

    _ENDPOINT = 'https://api.bybit.com'
    _SANDBOX_ENDPOINT = 'https://api-testnet.bybit.com'

    _WS_ENDPOINT: str
    _WS_SANDBOX_ENDPOINT: str

    _response_error = 'ret_msg'
    _response_result = 'result'

    @classmethod
    def get_symbol(cls, market: Market) -> str:
        return market.base + market.quote

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ws = BybitWebsocketClient(self._http,
                                        get_url=self._get_ws_url,
                                        on_message=self._on_message)
        # TODO: Fetch symbols https://bybit-exchange.github.io/docs/inverse/#t-querysymbol

    async def startup(self):
        self._logger.info('Connecting')
        await self._ws.connect()
        self._logger.info('Connected')

        resp = await self._ws.authenticate(self._api_key, self._api_secret)

        if resp['success']:
            await self._ws.subscribe("user.order.contractAccount")
            await self._ws.subscribe("user.execution.contractAccount")
            self._logger.info('Authed')
        else:
            return WebsocketError(reason='Could not authenticate')

    async def cleanup(self):
        await self._ws.close()

    def _get_ws_url(self) -> str:
        # https://bybit-exchange.github.io/docs/futuresV2/linear/#t-websocketauthentication
        return self._WS_SANDBOX_ENDPOINT if self.client.sandbox else self._WS_ENDPOINT

    @classmethod
    def _parse_exec(cls, raw_exec: Dict):

        if raw_exec['exec_type'] == "Trade":
            symbol = raw_exec["symbol"]
            commission = Decimal(raw_exec["exec_fee"])
            price = Decimal(get_multiple(raw_exec, "exec_price", "price"))
            qty = Decimal(raw_exec["exec_qty"])

            # Unify Inverse and Linear
            contract_type = get_contract_type(symbol)
            return Execution(
                symbol=symbol,
                price=price,
                qty=qty,
                commission=commission,
                time=(
                    cls.parse_ts(raw_exec["trade_time_ms"] / 1000)
                    if "trade_time_ms" in raw_exec else
                    parse_isoformat(raw_exec["trade_time"])
                ),
                side=Side.BUY if raw_exec["side"] == "Buy" else Side.SELL,
                type=ExecType.TRADE,
                inverse=contract_type == ContractType.INVERSE,
                settle='USD' if contract_type == ContractType.LINEAR else symbol[:-3]
            )

    @classmethod
    def _parse_exec_v3(cls, raw: Dict):

        # {
        #     "symbol": "BITUSDT",
        #     "execFee": "0.02022",
        #     "execId": "beba036f-9fb4-59a7-84b7-2620e5d13e1c",
        #     "execPrice": "0.674",
        #     "execQty": "50",
        #     "execType": "Trade",
        #     "execValue": "33.7",
        #     "feeRate": "0.0006",
        #     "lastLiquidityInd": "RemovedLiquidity",
        #     "leavesQty": "0",
        #     "orderId": "ddbea432-2bd7-45dd-ab42-52d920b8136d",
        #     "orderLinkId": "b001",
        #     "orderPrice": "0.707",
        #     "orderQty": "50",
        #     "orderType": "Market",
        #     "stopOrderType": "UNKNOWN",
        #     "side": "Buy",
        #     "execTime": "1659057535081",
        #     "closedSize": "0"
        # }
        if raw['execType'] == 'Trade':
            exec_type = ExecType.TRADE
        elif raw['execType'] == 'Funding':
            exec_type = ExecType.FUNDING
        else:
            return
        symbol = raw["symbol"]
        commission = Decimal(raw["execFee"])
        price = Decimal(get_multiple(raw, "execPrice"))
        qty = Decimal(raw["execQty"])

        # Unify Inverse and Linear
        contract_type = get_contract_type(symbol)
        return Execution(
            symbol=symbol,
            price=price,
            qty=qty,
            commission=commission,
            time=cls.parse_ms_dt(int(raw["execTime"])),
            side=Side.BUY if raw["side"] == "Buy" else Side.SELL,
            type=exec_type,
            inverse=contract_type == ContractType.INVERSE,
            settle='USD' if contract_type == ContractType.LINEAR else symbol[:-3]
        )

    @classmethod
    def _parse_order_v3(cls, raw: Dict):

        # {
        #     "symbol": "BTCUSD",
        #     "orderId": "ee013d82-fafc-4504-97b1-d92aca21eedd",
        #     "side": "Buy",
        #     "orderType": "Market",
        #     "stopOrderType": "UNKNOWN",
        #     "price": "21920.00",
        #     "qty": "200",
        #     "timeInForce": "ImmediateOrCancel",
        #     "orderStatus": "Filled",
        #     "triggerPrice": "0.00",
        #     "orderLinkId": "inv001",
        #     "createdTime": "1661338622771",
        #     "updatedTime": "1661338622775",
        #     "takeProfit": "0.00",
        #     "stopLoss": "0.00",
        #     "tpTriggerBy": "UNKNOWN",
        #     "slTriggerBy": "UNKNOWN",
        #     "triggerBy": "UNKNOWN",
        #     "reduceOnly": false,
        #     "closeOnTrigger": false,
        #     "triggerDirection": 0,
        #     "leavesQty": "0",
        #     "lastExecQty": "200",
        #     "lastExecPrice": "21282.00",
        #     "cumExecQty": "200",
        #     "cumExecValue": "0.00939761"
        # }

        if raw['orderStatus'] == 'Filled':
            symbol = raw["symbol"]
            commission = Decimal(raw["cumExecFee"])
            price = Decimal(raw["price"])
            qty = Decimal(raw["qty"])

            # Unify Inverse and Linear
            contract_type = get_contract_type(symbol)
            return Execution(
                symbol=symbol,
                price=price,
                qty=qty,
                commission=commission,
                time=cls.parse_ms_dt(int(raw["createdTime"])),
                side=Side.BUY if raw["side"] == "Buy" else Side.SELL,
                type=ExecType.TRADE,
                inverse=contract_type == ContractType.INVERSE,
                settle='USD' if contract_type == ContractType.LINEAR else symbol[:-3]
            )

    async def _on_message(self, ws: WebsocketManager, message: Dict):
        # https://bybit-exchange.github.io/docs/inverse/#t-websocketexecution
        print(message)
        topic = message.get('topic')
        if topic == "execution":
            for execution in (executions for executions in message["data"]):
                # {
                #     "symbol": "BTCUSD",
                #     "side": "Buy",
                #     "order_id": "xxxxxxxx-xxxx-xxxx-9a8f-4a973eb5c418",
                #     "exec_id": "xxxxxxxx-xxxx-xxxx-8b66-c3d2fcd352f6",
                #     "order_link_id": "",
                #     "price": "8300",
                #     "order_qty": 1,
                #     "exec_type": "Trade",
                #     "exec_qty": 1,
                #     "exec_fee": "0.00000009",
                #     "leaves_qty": 0,
                #     "is_maker": false,
                #     "trade_time": "2020-01-14T14:07:23.629Z"
                # }
                await self._on_execution(self._parse_exec(execution))
        elif topic == "user.execution.contractAccount":
            await self._on_execution(
                map_list(self._parse_exec_v3, message["data"])
            )

    # https://bybit-exchange.github.io/docs/inverse/?console#t-authentication
    def _sign_request(self, method: str, path: str, headers=None, params: OrderedDict = None, data=None, **kwargs):
        ts = int(time.time() * 1000)
        params['api_key'] = self._api_key
        params['timestamp'] = str(ts)

        copy = params.copy()
        params.clear()
        for key, val in sorted(copy.items()):
            params[key] = val

        query_string = urllib.parse.urlencode(sorted(params.items()))
        sign = hmac.new(
            self._api_secret.encode('utf-8'),
            query_string.encode('utf-8'), 'sha256'
        ).hexdigest()
        params['sign'] = sign

    @classmethod
    def _check_for_error(cls, response_json: Dict, response: ClientResponse):
        # https://bybit-exchange.github.io/docs/inverse/?console#t-errors
        code = get_multiple(response_json, "ret_code", "retCode")
        if code != 0:
            error: Type[ResponseError] = ResponseError
            if code in (10003, 10005, 33004):  # Invalid api key, Permission denied, Api Key Expired
                error = InvalidClientError

            if code == 10006:
                error = RateLimitExceeded

            raise error(
                root_error=ClientResponseError(response.request_info, (response,)),
                human=f'{get_multiple(response_json, "ret_msg", "retMsg")}, Code: {code}'
            )

    async def _get_paginated_v3(self,
                                params: dict = None,
                                valid: Callable = None,
                                **kwargs) -> list[dict]:
        page = True
        results = []

        while page:
            if page is not True:
                params['cursor'] = page
            elif 'cursor' in params:
                del params['cursor']
            response = await self.get(params=params, **kwargs)

            for result in response['list']:
                if not valid or valid(result):
                    results.append(result)
                else:
                    page = None
                    break
            else:
                page = response.get('nextPageCursor')

        return results

    async def _get_internal_transfers(self, since: datetime, wallet: Account) -> List[RawTransfer]:
        transfers = []
        params = {'status': Transfer.SUCCESS.value}
        if since:
            params['startTime'] = self._parse_date(since)

        res = await self.get('/asset/v1/private/transfer/list',
                             params=params)
        while res['list'] and False:
            transfers.extend(res['list'])
            if res['cursor']:
                params['cursor'] = res['cursor']
                params['direction'] = Direction.NEXT.value
                res = await self.get('/asset/v1/private/transfer/list',
                                     params=params)

        results = []

        params = {'status': Transfer.SUCCESS.value}
        if since:
            params['startTime'] = self._parse_date(since)

        def query_transfers():
            return self.get('/asset/v3/private/transfer/inter-transfer/list/query',
                            params=params)

        # res = await query_transfers()
        # while res['list']:
        #     transfers.extend(res['list'])
        #     params['cursor'] = res['nextPageCursor']
        #     res = await query_transfers()

        # {
        #     "transfer_id": "selfTransfer_c5ae452d-43e8-47e6-aa7c-d2bab57c0958",
        #     "coin": "BTC",
        #     "amount": "1",
        #     "from_account_type": "CONTRACT",
        #     "to_account_type": "SPOT",
        #     "timestamp": "1629965054",
        #     "status": "SUCCESS"
        # }
        for transfer in transfers:
            amount = transfer["amount"]
            if (
                    (
                            transfer["from_account_type"] == "CONTRACT"
                            and
                            transfer["to_account_type"] == "SPOT"
                            and
                            wallet == Account.DERIVATIVE
                    ) or (
                    transfer["from_account_type"] == "SPOT"
                    and
                    transfer["to_account_type"] == "CONTRACT"
                    and
                    wallet == Account.SPOT
            )):
                # Withdrawals are signaled by negative amounts
                amount *= -1
            results.append(RawTransfer(
                amount=amount,
                time=self.parse_ts(transfer["timestamp"]),
                coin=transfer["coin"],
                fee=None
            ))

        return results

    async def _get_internal_transfers_v3(self, since: datetime, account: Account) -> List[RawTransfer]:
        results = []

        params = {'status': Transfer.SUCCESS.value}
        if since:
            params['startTime'] = self._parse_date(since)

        transfers = await self._get_paginated_v3(path='/asset/v3/private/transfer/inter-transfer/list/query',
                                                 params=params)

        params['walletFundType'] = 'ExchangeOrderWithdraw'
        withdrawals = await self._get_paginated_v3(path='/contract/v3/private/account/wallet/fund-records',
                                                   params=params)

        params['walletFundType'] = 'ExchangeOrderDeposit'
        deposits = await self._get_paginated_v3(path='/contract/v3/private/account/wallet/fund-records',
                                                params=params)

        for record in itertools.chain(withdrawals, deposits):
            results.append(
                RawTransfer(
                    amount=Decimal(record['amount']) * (-1 if record['type'] == 'ExchangeOrderWithdraw' else 1),
                    time=self.parse_ms_dt(record['execTime']),
                    coin=record['coin'],
                    fee=None
                )
            )

        # {
        #     "transferId": "selfTransfer_cafc74cc-e28a-4ff6-b0e6-9e711376fc90",
        #     "coin": "USDT",
        #     "amount": "1000",
        #     "fromAccountType": "UNIFIED",
        #     "toAccountType": "SPOT",
        #     "timestamp": "1658986298000",
        #     "status": "SUCCESS"
        # }
        for transfer in transfers:
            if transfer["fromAccountType"] == account.value:
                # Withdrawal
                amount = transfer["amount"] * -1
            elif transfer["toAccountType"] == account.value:
                # Deposit
                amount = transfer["amount"]
            else:
                continue

            results.append(RawTransfer(
                amount=amount,
                time=self.parse_ts(transfer["timestamp"]),
                coin=transfer["coin"],
                fee=None
            ))

        return results

    def _parse_date(self, date: datetime | date = None):
        return int(date.timestamp() * 1000) if date else None


def get_contract_type(contract: str):
    if contract.endswith('USDT'):
        return ContractType.LINEAR
    else:
        return ContractType.INVERSE
