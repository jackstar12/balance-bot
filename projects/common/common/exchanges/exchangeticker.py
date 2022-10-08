from enum import Enum
import aiohttp
from typing import Dict


from common.models.observer import Observer, Observable


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
        if len(self._callbacks[channel.value]) == 1:
            await self._subscribe(channel, **kwargs)

    async def _subscribe(self, channel: Channel, **kwargs):
        raise NotImplementedError

    async def unsubscribe(self, channel: Channel, observer: Observer, **kwargs):
        self._callbacks[channel.value].detach(observer)
        if len(self._callbacks[channel.value]) == 0:
            await self._unsubscribe(channel, **kwargs)

    async def _unsubscribe(self, channel: Channel, **kwargs):
        raise NotImplementedError

    async def connect(self):
        raise NotImplementedError

    async def disconnect(self):
        raise NotImplementedError
