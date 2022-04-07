from typing import Callable
import aioredis
import pickle

class Messager:

    def __init__(self):
        self._redis = aioredis.Redis()
        self._redis.pubsub()

    def add_callback(self):
        pass

    def sub_channel(self, channel: str, callback: Callable):
        pass

    def pub_channel(self, channel: str, obj: object):
        self._redis.publish(channel, message=pickle.dumps(obj))

    def on_callback(self):
        pass

