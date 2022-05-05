import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Callable, Dict, Optional

import msgpack

from balancebot.common.database import redis
from balancebot.api.settings import settings
from balancebot.common.models.singleton import Singleton
import balancebot.common.utils as utils


class NameSpace(Enum):
    CLIENT = "client"
    ALERT = "alert"
    BALANCE = "balance"
    TRADE = "trade"
    EVENT = "event"
    COIN_STATS = "coinstats"
    TICKER = "ticker"
    PNL = "pnl"
    KEYSPACE = "__keyspace@0__"


class Category(Enum):
    NEW = "new"
    DELETE = "delete"
    UPDATE = "update"
    FINISHED = "finished"
    UPNL = "upnl"
    PNL = "pnl"
    REKT = "rekt"
    VOLUME = "volume"
    OI = "oi"
    SESSIONS = "sessions"


@dataclass
class ClientEdit:
    id: int
    archived: Optional[bool]
    invalid: Optional[bool]


class Messenger(Singleton):

    def init(self):
        self._redis = redis
        self._pubsub = self._redis.pubsub()
        self._listening = False

    def _wrap(self, coro, rcv_event=False):
        @wraps(coro)
        def wrapper(event: Dict, *args, **kwargs):
            logging.info(f'Redis Event: {event=} {args=} {kwargs=}')
            if rcv_event:
                data = event
            else:
                data = msgpack.unpackb(event['data'], raw=False)
            asyncio.create_task(utils.call_unknown_function(coro, data, *args, **kwargs))
        return wrapper

    async def listen(self):
        async for msg in self._pubsub.listen():
            logging.info(f'MSGG!!!! {msg}')

    async def sub(self, pattern=False, **kwargs):
        if pattern:
            await self._pubsub.psubscribe(**kwargs)
        else:
            await self._pubsub.subscribe(**kwargs)
        if not self._listening:
            self._listening = True
            asyncio.create_task(self.listen())

    def sub_channel(self, category: NameSpace, sub: Category, callback: Callable, channel_id: int = None, pattern=False, rcv_event=False):
        channel = utils.join_args(category.value, sub.value, channel_id)
        if pattern:
            channel += '*'
        kwargs = {channel: self._wrap(callback)}
        if settings.testing:
            logging.info(f'Sub: {kwargs}')
        asyncio.create_task(self.sub(pattern=pattern, rcv_event=False, **kwargs))

    def unsub_channel(self, category: NameSpace, sub: Category, channel_id: int = None, pattern=False):
        channel = utils.join_args(category.value, sub.value, channel_id)
        if pattern:
            channel += '*'
        if pattern:
            asyncio.create_task(self._pubsub.punsubscribe(channel))
        else:
            asyncio.create_task(self._pubsub.unsubscribe(channel))

    def pub_channel(self, category: NameSpace, sub: Category, obj: object, channel_id: int = None):
        ch = utils.join_args(category.value, sub.value, channel_id)
        if settings.testing:
            logging.info(f'Pub: {ch=} {obj=}')
        asyncio.create_task(self._redis.publish(ch, msgpack.packb(obj)))


if __name__ == '__main__':
    messenger = Messenger()
