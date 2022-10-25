import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Callable, Optional, Type, TypeVar, Generic, Any

import sqlalchemy.orm
from aioredis import Redis
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import event
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import object_session
from sqlalchemy.orm.util import identity_key

import core
from core import json as customjson
from database.dbmodels import Client, Balance, Chapter, Event, EventEntry
from database.dbmodels.alert import Alert
from database.dbmodels.editing import Journal
from database.dbmodels.mixins.serializer import Serializer
from database.dbmodels.pnldata import PnlData
from database.dbmodels.trade import Trade
from database.dbmodels.transfer import Transfer
from database.dbmodels.user import User
from database.dbsync import BaseMixin
from database.redis import TableNames

TTable = TypeVar('TTable', bound=BaseMixin)


@dataclass
class RedisNameSpace(Generic[TTable]):
    parent: 'Optional[RedisNameSpace]'
    name: 'str'
    table: 'Type[TTable]'
    id: Optional[str]

    @classmethod
    def from_table(cls,
                   table: Type[TTable],
                   parent: 'Optional[RedisNameSpace]' = None):
        return cls(
            parent=parent,
            name=table.__tablename__,
            table=table,
            id=f'{table.__tablename__}_id'
        )

    def get_ids(self, instance: TTable):
        if not instance:
            return {}
            # return self.parent.get_ids(instance)
        result = {self.id: instance.id}
        if self.parent:
            parent_id = getattr(instance, self.parent.id, None)
            if parent_id:
                result[self.parent.id] = getattr(instance, self.parent.id)
                try:
                    parent_instance = getattr(instance, self.parent.name, None)
                except InvalidRequestError:
                    parent_instance = None
                if not parent_instance:
                    session: sqlalchemy.orm.Session = object_session(instance)
                    parent_instance = session.identity_map.get(identity_key(self.parent.table, parent_id))
                result |= self.parent.get_ids(parent_instance)
        return result

    def format(self, *add, **ids):
        pattern = False
        for id in self.all_ids:
            if id not in ids:
                ids[id] = '*'
                pattern = True
        return self.fill(*add).format(**ids), pattern

    @property
    def all_ids(self):
        if self.parent:
            return [self.id, *self.parent.all_ids]
        return [self.id]

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.fill()

    def fill(self, *add):
        return core.join_args(self.parent, self.name, *add, '{' + self.id + '}')


class TradeSpace(RedisNameSpace):
    FINISHED = "finished"


class EventSpace(RedisNameSpace[Event]):
    def get_ids(self, instance: Event):
        return {
            'user_id': instance.owner_id,
            'event_id': instance.id
        }

    START = "start"
    REGISTRATION_START = "registration-start"
    END = "end"
    REGISTRATION_END = "registration-end"


USER = RedisNameSpace.from_table(User)

CLIENT = RedisNameSpace.from_table(Client, parent=USER)

BALANCE = RedisNameSpace.from_table(Balance, parent=CLIENT)
TRADE = TradeSpace.from_table(Trade, parent=CLIENT)
TRANSFER = RedisNameSpace.from_table(Transfer, parent=CLIENT)

PNL_DATA = RedisNameSpace.from_table(PnlData, parent=TRADE)

ALERT = RedisNameSpace.from_table(Alert, parent=USER)

EVENT = EventSpace.from_table(Event, parent=USER)
EVENT_SCORE = RedisNameSpace.from_table(EventEntry, parent=EVENT)

JOURNAL = RedisNameSpace.from_table(Journal, parent=USER)
CHAPTER = RedisNameSpace.from_table(Chapter, parent=JOURNAL)


by_names = core.groupby_unique(
    [USER, CLIENT, BALANCE, TRADE, PNL_DATA, ALERT, EVENT, EVENT_SCORE, JOURNAL, CHAPTER, TRANSFER],
    lambda space: space.name
)


class Category(Enum):
    NEW = "new"
    DELETE = "delete"
    UPDATE = "update"
    FINISHED = "finished"
    LIVE = "live"
    ADDED = "added"
    REMOVED = "removed"

    REKT = "rekt"


class Word(Enum):
    TIMESTAMP = "ts"


class ClientUpdate(BaseModel):
    id: int
    archived: Optional[bool]
    invalid: Optional[bool]
    premium: Optional[bool]


NameSpaceInput = RedisNameSpace | TableNames | Type[BaseMixin] | Any


class Messenger:

    def __init__(self, redis: Redis):
        self._redis = redis
        self._pubsub = self._redis.pubsub()
        self._listening = False
        self._logger = logging.getLogger('Messenger')

    def _wrap(self, coro, rcv_event=False):
        @wraps(coro)
        def wrapper(event: dict, *args, **kwargs):
            if rcv_event:
                data = event
            else:
                data = customjson.loads(event['data'])
            asyncio.create_task(
                core.call_unknown_function(coro, data, *args, **kwargs)
            )

        return wrapper

    async def listen(self):
        self._listening = True
        self._logger.info('Started Listening.')
        async for msg in self._pubsub.listen():
            self._logger.debug(msg)
        self._logger.info('Stopped Listening.')
        self._listening = False

    async def sub(self, pattern=False, **kwargs):
        self._logger.debug(f'Subscribing {pattern=} {kwargs=}')
        if pattern:
            await self._pubsub.psubscribe(**kwargs)
        else:
            await self._pubsub.subscribe(**kwargs)
        if not self._listening:
            asyncio.create_task(self.listen())

    async def unsub(self, channel: str, is_pattern=False):
        if is_pattern:
            await self._pubsub.punsubscribe(channel)
        else:
            await self._pubsub.unsubscribe(channel)

    # async def dec_sub(self, namespace: MessengerNameSpace, topic: Any, **ids):
    #    def wrapper(callback):

    @classmethod
    def get_namespace(cls, name: NameSpaceInput):
        if isinstance(name, RedisNameSpace):
            return name
        elif isinstance(name, Enum):
            return by_names.get(name.value)
        elif hasattr(name, '__tablename__'):
            return by_names.get(name.__tablename__)
        return by_names.get(str(name))

    def sub_channel(self, namespace: NameSpaceInput, topic: Any, callback: Callable, **ids):
        return self.bulk_sub(self.get_namespace(namespace), {topic: callback}, **ids)

    def unsub_channel(self, namespace: NameSpaceInput, topic: Any, **ids):
        channel, pattern = self.get_namespace(namespace).format(topic, **ids)
        return self.unsub(channel=channel, is_pattern=pattern)

    def pub_instance(self, instance: Serializer, topic: Any):
        ns = self.get_namespace(instance.__tablename__)
        return self.pub_channel(ns, topic, instance.serialize(), **ns.get_ids(instance))

    async def pub_channel(self, namespace: NameSpaceInput, topic: Any, obj: object, **ids):
        channel, pattern = self.get_namespace(namespace).format(topic, **ids)
        logging.debug(f'Pub: {channel=}')
        ret = await self._redis.publish(channel, customjson.dumps(obj))
        return ret

    # user:*:client:*:transfer:new
    # user:*:client:*:balance:new
    # user:*:client:455:trade:*:update
    # user:*:client:455:trade:new
    # user:*:client:*:trade:new
    # user:*:event:*:start
    # user:*:event:23:start
    # user:234f-345k:editing:23:chapter:new
    async def bulk_sub(self, namespace: NameSpaceInput, topics: dict[Any, Callable], **ids):
        subscription = {}
        pattern = False
        namespace = self.get_namespace(namespace)
        for topic, callback in topics.items():
            channel, pattern = namespace.format(topic, **ids)
            subscription[channel] = self._wrap(callback)
        await self.sub(pattern=pattern, **subscription)

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

    def listen_class(self,
                     target_cls: Type[Serializer],
                     identifier: str,
                     namespace: RedisNameSpace[Type[Serializer]],
                     sub: Category | str,
                     condition: Callable[[Serializer], bool] = None):
        @event.listens_for(target_cls, identifier)
        def handler(mapper, connection, target: target_cls):
            realtime = getattr(target, '__realtime__', True)
            if realtime and (not condition or condition(target)):
                asyncio.create_task(
                    self.pub_channel(namespace, sub,
                                     obj=jsonable_encoder(target.serialize(include_none=False)),
                                     **namespace.get_ids(target))
                )

    def listen_class_all(self, target_cls: Type[Serializer], namespace: RedisNameSpace = None):
        if not namespace:
            namespace = self.get_namespace(target_cls.__tablename__)

        if namespace is TRADE:
            def is_finished(trade: Trade):
                return not trade.is_open

            self.listen_class(target_cls, "after_update", namespace, TRADE.FINISHED, condition=is_finished)

        self.listen_class(target_cls, "after_insert", namespace, Category.NEW)
        self.listen_class(target_cls, "after_update", namespace, Category.UPDATE)
        self.listen_class(target_cls, "after_delete", namespace, Category.DELETE)
