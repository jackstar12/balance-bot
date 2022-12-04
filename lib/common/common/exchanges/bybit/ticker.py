from decimal import Decimal
from typing import Dict

from common.exchanges.bybit.derivatives import get_contract_type, ContractType
from common.exchanges.exchangeticker import ExchangeTicker, Channel
from common.exchanges.bybit.websocket import BybitWebsocketClient
from database.models.async_websocket_manager import WebsocketManager
from database.models.ticker import Ticker


class BybitDerivativesTicker(ExchangeTicker):
    _WS_LINEAR = 'wss://stream.bybit.com/contract/usdt/public/v3'
    _WS_LINEAR_SANDBOX = 'wss://stream-testnet.bybit.com/contract/usdt/public/v3'
    _WS_INVERSE = 'wss://stream.bybit.com/contract/inverse/public/v3'
    _WS_INVERSE_SANDBOX = 'wss://stream-testnet.bybit.com/contract/inverse/public/v3'

    EXCHANGE = 'bybit-derivatives'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._inverse = BybitWebsocketClient(self.session,
                                             self._WS_INVERSE_SANDBOX if self.sandbox else self._WS_INVERSE,
                                             self._on_message)

        self._linear = BybitWebsocketClient(self.session,
                                            self._WS_LINEAR_SANDBOX if self.sandbox else self._WS_LINEAR,
                                            self._on_message)

    def get_ws(self, symbol: str):
        contract = get_contract_type(symbol)
        if contract == ContractType.LINEAR:
            return self._linear
        elif contract == ContractType.INVERSE:
            return self._inverse

    def _subscribe(self, channel: Channel, **kwargs):
        # I have no idea why the values have to be compared
        if channel == Channel.TICKER:
            symbol = kwargs["symbol"]
            return self.get_ws(symbol).subscribe("trade", symbol)

    def _unsubscribe(self, channel: Channel, **kwargs):
        if channel == Channel.TICKER:
            symbol = kwargs["symbol"]
            return self.get_ws(symbol).unsubscribe("trade", symbol)

    async def connect(self):
        await self._inverse.connect()
        await self._linear.connect()

    async def disconnect(self):
        await self._inverse.close()
        await self._linear.close()

    async def _on_message(self, ws: WebsocketManager, message: Dict):
        if "data" in message:
            all_data = message["data"]
            if "trade" in message["topic"]:
                data = all_data[0]
                await self._callbacks.get(Channel.TICKER).notify(
                    Ticker(
                        symbol=data["symbol"],
                        exchange=self.EXCHANGE,
                        price=Decimal(data["price"]),
                    )
                )
