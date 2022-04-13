from enum import Enum
import aiohttp
from typing import Dict


from balancebot.common.models.observer import Observer, Observable


class Channel(Enum):
    TICKER = "ticker"
    TRADES = "trades"


class ExchangeTicker:

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        # Initialize Channels
        self._callbacks: Dict[str, Observable] = {}
        for channel in Channel:
            self._callbacks[channel.value] = Observable()

    async def subscribe(self, channel: Channel, observer: Observer, **kwargs):
        self._callbacks[channel.value].attach(observer)
        await self._subscribe(channel, **kwargs)

    async def _subscribe(self, channel: Channel, **kwargs):
        raise NotImplementedError

    async def unsubscribe(self, channel: Channel, observer: Observer, **kwargs):
        self._callbacks[channel.value].detach(observer)
        await self._unsubscribe(channel, **kwargs)

    async def _unsubscribe(self, channel: Channel, **kwargs):
        raise NotImplementedError

    def connect(self):
        raise NotImplementedError
