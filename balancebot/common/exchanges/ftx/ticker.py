from datetime import datetime
import time

from balancebot.collector.exchangeticker import ExchangeTicker, Channel
from balancebot.common.exchanges.ftx.websocket import FtxWebsocketClient
from balancebot.common.models.ticker import Ticker
from balancebot.common.models.trade import Trade


class FtxTicker(ExchangeTicker):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ws = FtxWebsocketClient(self.session, on_message_callback=self._on_message)

    async def connect(self):
        await self._ws.connect()

    async def _subscribe(self, channel: Channel, **kwargs):
        if channel.value == Channel.TICKER.value:
            await self._ws.get_ticker(kwargs['symbol'])
        elif channel.value is Channel.TRADES.value:
            await self._ws.get_trades(kwargs['symbol'])

    async def _on_message(self, msg):

        channel = msg['channel']
        data = msg['data']
        market = msg['market']

        if channel == 'trades':
            data = data[0]
            await self._callbacks.get(Channel.TRADES.value).notify(
                Trade(
                    symbol=market,
                    price=data['price'],
                    size=data['size'],
                    time=datetime.fromisoformat(data['time']),
                    side=data['side'],
                    perp='PERP' in market,
                    exchange='ftx'
                )
            )
        elif channel == 'ticker':
            await self._callbacks.get(Channel.TICKER.value).notify(
                Ticker(
                    symbol=market,
                    price=data['last'],
                    ts=data['time'],
                    exchange='ftx'
                )
            )

