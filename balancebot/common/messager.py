import asyncio
from typing import Callable
import aioredis
import pickle

from balancebot.common import utils


class Messager:

    def __init__(self):
        self._redis = aioredis.Redis()
        self._pubsub = self._redis.pubsub()

    def add_callback(self):
        pass

    def sub_channel(self, channel: str, callback: Callable):
        asyncio.create_task(self._listen_to_channel(channel, callback))

    def pub_channel(self, channel: str, obj: object):
        self._redis.publish(channel, message=pickle.dumps(obj))

    def on_callback(self):
        pass

    async def _listen_to_channel(self, channel: str, callback: Callable):
        ch = self._pubsub.subscribe(channel)
        async for msg in ch.iter():
            await utils.call_unknown_function(callback, msg)
