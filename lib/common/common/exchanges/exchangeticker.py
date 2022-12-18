import aiohttp
from typing import Dict, NamedTuple

from core import json
from database.dbmodels.client import ExchangeInfo
from database.models.observer import Observer, Observable
from common.exchanges.channel import Channel


class Subscription(NamedTuple):
    channel: Channel
    kwargs: dict

    @classmethod
    def get(cls, channel: Channel, **kwargs):
        return cls(channel=channel, kwargs=kwargs)

    def __hash__(self):
        return self.channel.__hash__() + json.dumps(self.kwargs).__hash__()


class ExchangeTicker:

    NAME: str

    def __init__(self, session: aiohttp.ClientSession, sandbox: bool):
        self.session = session
        self.info = ExchangeInfo(name=self.NAME, sandbox=sandbox)
        # Initialize Channels
        self._callbacks: Dict[Subscription, Observable] = {}


    async def subscribe(self, sub: Subscription, observer: Observer):
        observable = self._callbacks.get(sub)
        if not observable:
            observable = Observable()
            observable.attach(observer)
            self._callbacks[sub] = observable
            await self._subscribe(sub)
        else:
            observable.attach(observer)

    async def _subscribe(self, sub: Subscription):
        raise NotImplementedError

    async def unsubscribe(self, sub: Subscription, observer: Observer):
        observable = self._callbacks[sub]
        if observable:
            observable.detach(observer)
            if len(observable) == 0:
                await self._unsubscribe(sub)

    async def _unsubscribe(self, sub: Subscription):
        raise NotImplementedError

    async def connect(self):
        raise NotImplementedError

    async def disconnect(self):
        raise NotImplementedError
