import asyncio
from asyncio import current_task
import dotenv
import os
import aioredis
from sqlalchemy import delete, select

from sqlalchemy.orm import sessionmaker, joinedload, selectinload
from sqlalchemy.ext.asyncio import async_scoped_session, AsyncSession, create_async_engine
from sqlalchemy.sql import Select

from balancebot.api.database import Meta, Base

dotenv.load_dotenv()

SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI')
assert SQLALCHEMY_DATABASE_URI

engine = create_async_engine(
    'postgresql+asyncpg://postgres:postgres@localhost:5432/single-user'
)
async_maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
async_session: AsyncSession = async_scoped_session(async_maker, scopefunc=current_task)

redis = aioredis.Redis()


async def db(stmt):
    return await async_session.execute(stmt)


def db_select(cls, **filters):
    return db_first(select(cls).filter_by(**filters))


async def db_all(stmt: Select, **eager):
    if eager:
        stmt = db_eager(stmt, **eager)
    return (await async_session.scalars(stmt)).unique().all()


async def db_first(stmt: Select, **eager):
    if eager:
        stmt = db_eager(stmt, **eager)
    return (await async_session.scalars(stmt.limit(1))).first()


async def db_unique(stmt: Select, **eager):
    if eager:
        stmt = db_eager(stmt, **eager)
    return (await async_session.scalars(stmt.limit(1))).unique().first()


async def db_del_filter(cls, **kwargs):
    return await db(delete(cls).filter_by(**kwargs))


def db_joins(option, **kwargs):
    for key in kwargs.keys():
        if isinstance(kwargs[key], bool):
            option.joinedload(key)
        if isinstance(kwargs[key], dict):
            db_joins(option, **kwargs)


def db_eager(stmt: Select, **kwargs):
    options = []
    for key in kwargs.keys():
        option = joinedload(key)
        if isinstance(kwargs[key], dict):
            db_joins(option, **kwargs[key])
        options.append(option)
    return stmt.options(*options)



if __name__ == '__main__':
    print(asyncio.run(redis.get('test')))


