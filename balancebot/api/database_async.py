import asyncio
from asyncio import current_task
from typing import List, Tuple, Union

import dotenv
import os
import aioredis
from sqlalchemy import delete, select, Column

from sqlalchemy.orm import sessionmaker, joinedload, selectinload, InstrumentedAttribute
from sqlalchemy.ext.asyncio import async_scoped_session, AsyncSession, create_async_engine
from sqlalchemy.sql import Select

dotenv.load_dotenv()

SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI')
assert SQLALCHEMY_DATABASE_URI

engine = create_async_engine(
    'postgresql+asyncpg://postgres:postgres@localhost:5432/single-user'
)
async_maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
async_session: AsyncSession = async_scoped_session(async_maker, scopefunc=current_task)
# }+dg}E\w37/jWpSP
redis = aioredis.Redis(host='redis-16564.c300.eu-central-1-1.ec2.cloud.redislabs.com',
                       port=16564,
                       password='usTzjlI4SKy92HE6PGXgvTsaIQMdYWgo')


async def db(stmt):
    return await async_session.execute(stmt)


def db_select(cls, eager=None, **filters):
    if eager:
        return db_unique(db_eager(select(cls), *eager).filter_by(**filters))
    else:
        return db_first(select(cls).filter_by(**filters))


def db_select_all(cls, eager=None, **filters):
    if eager:
        return db_all(db_eager(select(cls), *eager).filter_by(**filters))
    return db_all(select(cls).filter_by(**filters))


async def db_all(stmt: Select, *eager):
    if eager:
        stmt = db_eager(stmt, *eager)
    return (await async_session.scalars(stmt)).unique().all()


async def db_first(stmt: Select, *eager):
    if eager:
        stmt = db_eager(stmt, *eager)
    return (await async_session.scalars(stmt.limit(1))).unique().first()


async def db_unique(stmt: Select, *eager):
    if eager:
        stmt = db_eager(stmt, *eager)
    return (await async_session.scalars(stmt.limit(1))).unique().first()


async def db_del_filter(cls, **kwargs):
    return await db(delete(cls).filter_by(**kwargs))


def db_joins(stmt: Select, option, *eager: List[Union[InstrumentedAttribute, Tuple[Column, List]]]):
    for col in eager:
        if isinstance(col, Tuple):
            option = option.joinedload(col[0])
            if isinstance(col[1], list):
                stmt = db_joins(stmt, option, *col[1])
            elif isinstance(col[1], tuple):
                stmt = db_joins(stmt, option, col[1])
            elif col[1] == '*':
                option.joinedload('*')
        else:
            stmt = stmt.options(option.joinedload(col))
    return stmt


def apply_option(stmt: Select, col: Union[Column, str], root=None, joined=False):
    if root:
        if joined:
            stmt = stmt.options(root.joinedload(col))
        else:
            stmt = stmt.options(root.selectinload(col))
    else:
        if joined:
            stmt = stmt.options(joinedload(col))
        else:
            stmt = stmt.options(selectinload(col))
    return stmt


def db_eager(stmt: Select, *eager: Union[Column, Tuple[Column, Union[Tuple, InstrumentedAttribute, List, str]]], root=None, joined=False):
    for col in eager:
        if isinstance(col, Tuple):
            if root is None:
                path = joinedload(col[0])
            else:
                path = root.joinedload(col[0])
            if isinstance(col[1], list):
                stmt = db_eager(stmt, *col[1], root=path)
            elif isinstance(col[1], InstrumentedAttribute) or isinstance(col[1], Tuple):
                stmt = db_eager(stmt, col[1], root=path)
            elif col[1] == '*':
                stmt = apply_option(stmt, '*', root=root, joined=joined)
                stmt = stmt.options(root.joinedload('*'))
        else:
            stmt = apply_option(stmt, col, root=root, joined=joined)
    return stmt


if __name__ == '__main__':
    print(asyncio.run(redis.get('test')))
