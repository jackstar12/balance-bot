import asyncio
import logging
from enum import Enum
from functools import wraps
from typing import Callable, Dict, Optional

from aioredis import Redis
from pydantic import BaseModel

import tradealpha.common.utils as utils
from tradealpha.common import customjson


class NameSpace(Enum):
    CLIENT = "client"
    USER = "user"
    ALERT = "alert"
    BALANCE = "balance"
    TRADE = "trade"
    EVENT = "event"
    COIN_STATS = "coinstats"
    TICKER = "ticker"
    PNL = "pnl"
    KEYSPACE = "__keyspace@0__"
    CACHE = "cache"


class Category(Enum):
    NEW = "new"
    DELETE = "delete"
    UPDATE = "update"
    FINISHED = "finished"
    UPNL = "upnl"
    ADDED = "added"
    REMOVED = "removed"
    SIGNIFICANT_PNL = "significantpnl"
    REKT = "rekt"
    VOLUME = "volume"
    OI = "oi"
    SESSIONS = "sessions"
    BASIC = "basic"
    ADVANCED = "advanced"


class Word(Enum):
    TIMESTAMP = "ts"


class ClientUpdate(BaseModel):
    id: int
    archived: Optional[bool]
    invalid: Optional[bool]
    premium: Optional[bool]


class Messenger:

    def __init__(self, redis: Redis):
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
            asyncio.create_task(
                utils.call_unknown_function(coro, data, *args, **kwargs)
            )

        return wrapper

    async def listen(self):
        logging.info('Started Listening.')
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

    async def unsub(self, channel: str, is_pattern=False):
        if is_pattern:
            await self._pubsub.punsubscribe(channel)
        else:
            await self._pubsub.unsubscribe(channel)

    async def sub_channel(self, category: NameSpace, sub: Category | str, callback: Callable, channel_id: int = None,
                          pattern=False, rcv_event=False):
        channel = utils.join_args(category, sub, channel_id)
        if pattern:
            channel += '*'
        kwargs = {channel: self._wrap(callback)}
        logging.info(f'Sub: {kwargs}')
        await self.sub(pattern=pattern, **kwargs)

    async def unsub_channel(self, category: NameSpace, sub: Category, channel_id: int = None, pattern=False):
        channel = utils.join_args(category.value, sub.value, channel_id)
        await self.unsub(channel, pattern)

    async def setup_waiter(self, channel: str, is_pattern=False, timeout=.25):
        fut = asyncio.get_running_loop().create_future()
        await self.sub(
            pattern=is_pattern,
            **{channel: fut.set_result}
        )

        async def wait():
            try:
                return await asyncio.wait_for(fut, timeout)
            except asyncio.exceptions.TimeoutError:
                return False
            finally:
                await self.unsub(channel, is_pattern)

        return wait

    def pub_channel(self, category: NameSpace, sub: Category, obj: object, channel_id: int = None):
        ch = utils.join_args(category.value, sub.value, channel_id)
        logging.info(f'Pub: {ch=} {obj=}')
        return asyncio.create_task(self._redis.publish(ch, customjson.dumps(obj)))
