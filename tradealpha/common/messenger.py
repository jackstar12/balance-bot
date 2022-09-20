import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Callable, Dict, Optional, Type, TypeVar, Generic, Any

import sqlalchemy.orm
import sqlalchemy_utils
from aioredis import Redis
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import event
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import object_session
from sqlalchemy.orm.util import identity_key
from tradealpha.common.redis import TableNames
import tradealpha.common.utils as utils
from tradealpha.common.dbmodels import Client, Balance, Chapter, Event
from tradealpha.common.dbmodels.alert import Alert
from tradealpha.common.dbmodels.journal import Journal
from tradealpha.common.dbmodels.pnldata import PnlData
from tradealpha.common.dbmodels.trade import Trade
from tradealpha.common.dbmodels.user import User
from tradealpha.common.dbsync import Base
from tradealpha.common.dbmodels.mixins.serializer import Serializer
from tradealpha.common import customjson

TTable = TypeVar('TTable', bound=Base)


@dataclass
class MessengerNameSpace(Generic[TTable]):
    parent: 'Optional[MessengerNameSpace]'
    name: 'str'
    table: 'Type[TTable]'
    id: Optional[str]

    class Category(Enum):
        NEW = "new"
        DELETE = "delete"
        UPDATE = "update"

    @classmethod
    def from_table(cls,
                   table: Type[TTable],
                   parent: 'Optional[MessengerNameSpace]' = None):
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
        return utils.join_args(self.parent, self.name, *add, '{' + self.id + '}')


class TradeSpace(MessengerNameSpace):
    FINISHED = "finished"


class EventSpace(MessengerNameSpace[Event]):
    def get_ids(self, instance: Event):
        return {
            'user_id': instance.owner_id,
            'event_id': instance.id
        }

    START = "start"
    REGISTRATION_START = "registration-start"
    END = "end"
    REGISTRATION_END = "registration-end"


USER = MessengerNameSpace.from_table(User)
CLIENT = MessengerNameSpace.from_table(Client, parent=USER)
BALANCE = MessengerNameSpace.from_table(Balance, parent=CLIENT)
TRADE = TradeSpace.from_table(Trade, parent=CLIENT)
PNL_DATA = MessengerNameSpace.from_table(PnlData, parent=TRADE)
ALERT = MessengerNameSpace.from_table(Alert, parent=USER)
EVENT = EventSpace.from_table(Event, parent=USER)
JOURNAL = MessengerNameSpace.from_table(Journal, parent=USER)
CHAPTER = MessengerNameSpace.from_table(Chapter, parent=JOURNAL)


by_names = utils.groupby_unique(
    [USER, CLIENT, BALANCE, TRADE, PNL_DATA, ALERT, EVENT, JOURNAL, CHAPTER],
    lambda space: space.name
)


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
    START = "start"
    REGISTRATION_START = "registration-start"
    END = "end"
    REGISTRATION_END = "registration-end"


class Word(Enum):
    TIMESTAMP = "ts"


class ClientUpdate(BaseModel):
    id: int
    archived: Optional[bool]
    invalid: Optional[bool]
    premium: Optional[bool]


NameSpaceInput = MessengerNameSpace | TableNames


class Messenger:

    def __init__(self, redis: Redis):
        self._redis = redis
        self._pubsub = self._redis.pubsub()
        self._listening = False
        self._logger = logging.getLogger('Messenger')

    def _wrap(self, coro, rcv_event=False):
        @wraps(coro)
        def wrapper(event: dict, *args, **kwargs):
            self._logger.info(f'Redis Event: {event=} {args=} {kwargs=}')
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
            pass

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

    # async def dec_sub(self, namespace: MessengerNameSpace, topic: Any, **ids):
    #    def wrapper(callback):

    @classmethod
    def get_namespace(cls, name: Any):
        if isinstance(name, MessengerNameSpace):
            return name
        elif isinstance(name, TableNames):
            return by_names.get(name.value)
        return by_names.get(str(name))

    def v2_sub_channel(self, namespace: NameSpaceInput, topic: Any, callback: Callable, **ids):
        return self.v2_bulk_sub(self.get_namespace(namespace), {topic: callback}, **ids)

    def v2_unsub_channel(self, namespace: NameSpaceInput, topic: Any, **ids):
        channel, pattern = self.get_namespace(namespace).format(topic, **ids)
        return self.unsub(channel=channel, is_pattern=pattern)

    def v2_pub_instance(self, instance: Serializer, topic: Any):
        ns = self.get_namespace(instance.__tablename__)
        return self.v2_pub_channel(ns, topic, instance.serialize(), **ns.get_ids(instance))

    async def v2_pub_channel(self, namespace: NameSpaceInput, topic: Any, obj: object, **ids):
        channel, pattern = self.get_namespace(namespace).format(topic, **ids)
        logging.info(f'Pub: {channel=} {obj=}')
        # await self._redis.publish(channel, customjson.dumps({'ids': ids, 'obj': obj}))
        await self._redis.publish(channel, customjson.dumps(obj))

    # user:*:client:*:transfer:new
    # user:*:client:*:balance:new
    # user:*:client:455:trade:*:update
    # user:*:client:455:trade:new
    # user:*:client:*:trade:new
    # user:*:event:*:start
    # user:*:event:23:start
    # user:234f-345k:journal:23:chapter:new
    async def v2_bulk_sub(self, namespace: NameSpaceInput, topics: dict[Any, Callable], **ids):
        subscription = {}
        pattern = False
        namespace = self.get_namespace(namespace)
        for topic, callback in topics.items():
            channel, pattern = namespace.format(topic, **ids)
            subscription[channel] = self._wrap(callback)
        await self.sub(pattern=pattern, **subscription)

    async def sub_channel(self, namespace: TableNames, sub: Category | str, callback: Callable, channel_id: int = None,
                          pattern=False, rcv_event=False):
        channel = utils.join_args(namespace, sub, channel_id)
        if pattern:
            channel += '*'
        kwargs = {channel: self._wrap(callback)}
        logging.info(f'Sub: {kwargs}')
        await self.sub(pattern=pattern, **kwargs)

    async def unsub_channel(self, category: TableNames, sub: Category, channel_id: int = None, pattern=False):
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

    def pub_channel(self, category: TableNames | str, sub: Category, obj: object, channel_id: int = None):
        ch = utils.join_args(category, sub.value, channel_id)
        logging.info(f'Pub: {ch=} {obj=}')
        return asyncio.create_task(self._redis.publish(ch, customjson.dumps(obj)))

    def _listen(self,
                target_cls: Type[Serializer, Base],
                identifier: str,
                namespace: MessengerNameSpace[Type[Serializer]],
                sub: Category):
        @event.listens_for(target_cls, identifier)
        def on_insert(mapper, connection, target: target_cls):
            if target.__realtime__ is not False:
                asyncio.create_task(
                    self.v2_pub_channel(namespace, sub,
                                        obj=jsonable_encoder(target.serialize(include_none=False)),
                                        **namespace.get_ids(target))
                )

    def listen_class(self, target_cls: Type[Serializer, Base], namespace: MessengerNameSpace = None):
        if not namespace:
            namespace = self.get_namespace(target_cls.__tablename__)
        self._listen(target_cls, "after_insert", namespace, Category.NEW)
        self._listen(target_cls, "after_update", namespace, Category.UPDATE)
        self._listen(target_cls, "after_delete", namespace, Category.DELETE)
