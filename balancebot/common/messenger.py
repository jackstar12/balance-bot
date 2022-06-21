import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Callable, Dict, Optional

import msgpack
from pydantic import BaseModel

from balancebot.common import customjson
from balancebot.common.config import TESTING
from balancebot.common.dbsync import redis
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
    SIGNIFICANT_PNL = "significantpnl"
    REKT = "rekt"
    VOLUME = "volume"
    OI = "oi"
    SESSIONS = "sessions"


class ClientUpdate(BaseModel):
    id: int
    archived: Optional[bool]
    invalid: Optional[bool]
    premium: Optional[bool]


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
                data = customjson.loads(event['data'])
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
        logging.info(f'Sub: {kwargs}')
        asyncio.create_task(self.sub(pattern=pattern, **kwargs))

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
        logging.info(f'Pub: {ch=} {obj=}')
        asyncio.create_task(self._redis.publish(ch, customjson.dumps(obj)))


if __name__ == '__main__':
    messenger = Messenger()
