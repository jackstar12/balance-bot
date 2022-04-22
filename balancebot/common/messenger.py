import asyncio
import logging
from enum import Enum
from functools import wraps
from typing import Callable, Dict

import msgpack

from balancebot.api.database import redis
import balancebot.collector.usermanager as usermanager
from balancebot.api.settings import settings
from balancebot.common import utils
from balancebot.common.models.singleton import Singleton


class Category(Enum):
    CLIENT = "client"
    ALERT = "alert"
    BALANCE = "balance"
    TRADE = "trade"
    EVENT = "event"
    COIN_STATS = "coinstats"


class SubCategory(Enum):
    NEW = "new"
    DELETE = "delete"
    UPDATE = "update"
    FINISHED = "finished"
    UPNL = "upnl"
    REKT = "rekt"
    VOLUME = "volume"
    OI = "oi"


class Messenger(Singleton):

    def init(self):
        self._redis = redis
        self._pubsub = self._redis.pubsub()
        self._um = usermanager.UserManager()
        self._listening = False

    def _wrap(self, coro):
        @wraps(coro)
        def wrapper(event: Dict, *args, **kwargs):
            logging.info(f'Redis Event: {event=} {args=} {kwargs=}')
            data = msgpack.unpackb(event['data'], raw=False)
            asyncio.create_task(utils.call_unknown_function(coro, data, *args, **kwargs))
        return wrapper

    async def listen(self):
        async for msg in self._pubsub.listen():
            logging.info(f'MSGG!!!! {msg}')

    async def _sub(self, pattern=False, **kwargs):
        if pattern:
            await self._pubsub.psubscribe(**kwargs)
        else:
            await self._pubsub.subscribe(**kwargs)
        if not self._listening:
            self._listening = True
            asyncio.create_task(self.listen())

    def sub_channel(self, category: Category, sub: SubCategory, callback: Callable, channel_id: int = None, pattern=False):
        channel = self._join(category.value, sub.value, channel_id)
        if pattern:
            channel += '*'
        kwargs = {channel: self._wrap(callback)}
        if settings.testing:
            logging.info(f'Sub: {kwargs}')
        asyncio.create_task(self._sub(pattern=pattern, **kwargs))

    def unsub_channel(self, category: Category, sub: SubCategory, channel_id: int = None, pattern=False):
        channel = self._join(category.value, sub.value, channel_id)
        if pattern:
            channel += '*'
        if pattern:
            asyncio.create_task(self._pubsub.punsubscribe(channel))
        else:
            asyncio.create_task(self._pubsub.unsubscribe(channel))

    def pub_channel(self, category: Category, sub: SubCategory, obj: object, channel_id: int = None):
        ch = self._join(category.value, sub.value, channel_id)
        if settings.testing:
            logging.info(f'Pub: {ch=} {obj=}')
        asyncio.create_task(self._redis.publish(ch, msgpack.packb(obj)))

    def _join(self, *args, denominator=':'):
        return denominator.join([str(arg) for arg in args if arg])


if __name__ == '__main__':
    messenger = Messenger()
