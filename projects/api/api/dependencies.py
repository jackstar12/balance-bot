import asyncio
import logging
import time
from http import HTTPStatus
from typing import Type
from uuid import UUID

from fastapi import Depends
from fastapi import Request, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.authenticator import Authenticator
from api.models.filterparam import FilterParam
from api.settings import settings
from database.dbasync import redis, db_eager, db_unique, async_maker
from database.dbmodels.user import User
from common.messenger import Messenger
from database.models import BaseModel
from database.redis import rpc

default_authenticator = Authenticator(
    redis,
    session_expiration=48 * 60 * 60,
    session_cookie_name=settings.session_cookie_name
)

messenger = Messenger(redis)


def get_authenticator() -> Authenticator:
    return default_authenticator


def get_dc_rpc_client():
    return rpc.Client('discord', redis, timeout=10)


async def get_db() -> AsyncSession:
    logging.info('Creating session')
    db: AsyncSession = async_maker()
    # The cleanup code has to be shielded, see:
    # https://github.com/tiangolo/fastapi/issues/4719
    try:
        yield db
    except SQLAlchemyError:
        await asyncio.shield(db.rollback())
    finally:
        await asyncio.shield(db.close())


async def get_user_id(request: Request, authenticator = Depends(get_authenticator)) -> UUID:
    return await authenticator.verify_id(request)


def get_messenger():
    return messenger


class CurrentUserDep:
    def __init__(self, *eager_loads):
        self.base_stmt = db_eager(select(User).options(joinedload(User.events)), *eager_loads)
        self._eager_loads = eager_loads

    async def __call__(self,
                       request: Request,
                       authenticator = Depends(get_authenticator),
                       db: AsyncSession = Depends(get_db)):
        uuid = await authenticator.verify_id(request)
        ts1 = time.perf_counter()
        user = await db_unique(self.base_stmt, session=db) if uuid else None
        ts2 = time.perf_counter()
        print(ts2 - ts1)
        if not user:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail='Invalid session'
            )
        return user


CurrentUser = CurrentUserDep()


class FilterQueryParamsDep:
    def __init__(self,
                 filter_model: Type[BaseModel]):
        self.filter_model = filter_model

    def __call__(self, request: Request):
        filters = []
        for key in request.query_params.keys():
            try:
                filters.append(FilterParam.parse(key, request.query_params.getlist(key), self.filter_model))
            except ValueError:
                continue
        return filters
