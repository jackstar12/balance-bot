import os
from asyncio import Future
from dataclasses import dataclass
from typing import Any, Callable, Optional

import pytest
from aioredis import Redis

from api.models.trade import Trade

from tests.mockexchange import MockExchange
from tradealpha.common.dbmodels import Event, Client, EventScore
from tradealpha.common import utils
from tradealpha.api.app import app
from tradealpha.common.dbsync import Base
from tradealpha.common.dbasync import REDIS_URI
from tradealpha.common.messenger import Messenger, NameSpaceInput

import asyncio

import aioredis

from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tradealpha.common import customjson
from tradealpha.common.exchanges import EXCHANGES

pytestmark = pytest.mark.anyio


SA_DATABASE_TESTING_URI = os.environ.get('DATABASE_TESTING_URI')
assert SA_DATABASE_TESTING_URI


EXCHANGES['mock'] = MockExchange


@pytest.fixture(scope='session')
def engine():
    return create_async_engine(
        f'postgresql+asyncpg://{SA_DATABASE_TESTING_URI}',
        json_serializer=customjson.dumps_no_bytes,
        json_deserializer=customjson.loads,
    )


@pytest.fixture(scope='session')
async def tables(engine):
    async with engine.begin() as conn:
        #await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(scope='session')
def session_maker(tables, engine):
    return sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope='function')
async def db(tables, engine, session_maker) -> AsyncSession:
    async with session_maker() as db:
        yield db


@pytest.fixture(scope='session')
def redis() -> Redis:
    return aioredis.from_url(REDIS_URI)


@pytest.fixture(scope='session')
def messenger(redis) -> Messenger:
    messenger = Messenger(redis=redis)
    messenger.listen_class(Event)
    messenger.listen_class(Client)
    messenger.listen_class(EventScore)
    messenger.listen_class(Trade)
    return messenger


@dataclass
class Channel:
    ns: NameSpaceInput
    topic: Any
    validate: Callable[[dict], bool] = None


@dataclass
class Messages:
    channels: list[Channel]
    results: dict[str, Future]
    messenger: Messenger

    async def wait(self, timeout: float = 1):
        waiter = asyncio.gather(*self.results.values())
        try:
            await asyncio.wait_for(waiter, timeout)
        except asyncio.exceptions.TimeoutError:
            pytest.fail(f'Missed following messages:')
            #pytest.fail(f'Missed following messages:' + '\n\t'.join(name for name, fut in self.results.values() if not fut.done()))

    @classmethod
    def create(cls, *channels: Channel, messenger: Messenger):
        loop = asyncio.get_running_loop()
        return cls(
            channels=list(channels),
            results={
                c.ns.name: loop.create_future()
                for c in channels
            },
            messenger=messenger
        )

    async def __aenter__(self):
        for channel in self.channels:
            def callback(data):
                if not channel.validate or channel.validate(data):
                    self.results[channel.ns.name].set_result(data)

            await self.messenger.v2_sub_channel(
                channel.ns,
                channel.topic,
                callback
            )
        return self

    async def __aexit__(self, *args):
        for channel in self.channels:
            await self.messenger.v2_unsub_channel(channel.ns.name, channel.topic)


@pytest.fixture(scope='function')
async def redis_messages(request, messenger):
    async with Messages.create(*request.param, messenger=messenger) as messages:
        yield messages


@pytest.fixture(scope='session')
def anyio_backend():
    return 'asyncio'
