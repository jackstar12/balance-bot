import asyncio
from functools import wraps

import aiohttp
import pytest
import requests
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete

import tradealpha.collector.collector as collector
from tradealpha.common.dbasync import db_select
from tradealpha.collector.services.balanceservice import ExtendedBalanceService, BasicBalanceService
from tradealpha.collector.services.baseservice import BaseService
from tradealpha.collector.services.dataservice import DataService
from tradealpha.common import utils
from tradealpha.common.dbmodels.client import Client
from tradealpha.common.messenger import TableNames, Category
from tests.conftest import RedisMessages, Channel
from tradealpha.common.dbmodels.user import User
from tradealpha.common.exchanges import CCXT_CLIENTS

pytestmark = pytest.mark.anyio


@pytest.fixture(scope='session')
def session():
    with requests.Session() as session:
        yield session


def run_service(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        async with func(*args, **kwargs) as service:
            await utils.call_unknown_function(service.init)
            task = asyncio.create_task(
                utils.call_unknown_function(service.run_forever)
            )
            yield service
            task.cancel()

    return wrapper


@pytest.fixture(scope='session')
async def service_args(messenger, redis, session_maker):
    scheduler = AsyncIOScheduler(
        executors={'default': AsyncIOExecutor()}
    )
    async with aiohttp.ClientSession() as session:
        scheduler.start()
        return session, messenger, redis, scheduler, session_maker


@pytest.fixture(scope='session')
@run_service
def data_service(service_args):
    return DataService(*service_args)


@pytest.fixture(scope='session')
@run_service
def pnl_service(data_service, service_args):
    return ExtendedBalanceService(*service_args, data_service=data_service)


@pytest.fixture(scope='session')
@run_service
def balance_service(data_service, service_args):
    return BasicBalanceService(*service_args, data_service=data_service)


@pytest.fixture
async def test_user(db):

    user = await db_select(User,
                           eager=[],
                           session=db,
                           email=User.mock().email)
    if not user:
        user = User.mock()
        db.add(user)
        await db.commit()

    yield user
    await db.execute(
        delete(User).where(User.id == user.id)
    )
    await db.commit()


@pytest.fixture
async def db_client(request, time, db, test_user, messenger) -> Client:

    async with RedisMessages.create(
        Channel(TableNames.CLIENT, Category.UPDATE, validate=lambda data: data['state'] == 'OK'),
        messenger=messenger
    ) as listener:
        client: Client = request.param.create(test_user)
        client.last_execution_sync = time
        client.last_transfer_sync = time
        db.add(client)
        await db.commit()
        await listener.wait(5)

    try:
        yield client
    finally:
        await db.delete(client)
        await db.commit()
        await listener.wait(.5)


@pytest.fixture
def ccxt_client(db_client, session):
    ccxt_class = CCXT_CLIENTS[db_client.exchange]
    ccxt = ccxt_class({
        'api_key': db_client.api_key,
        'secret': db_client.api_secret,
        'session': session,
        **(db_client.extra_kwargs or {})
    })

    ccxt.set_sandbox_mode(db_client.sandbox)

    return ccxt

