import asyncio
import logging
import time
from http import HTTPStatus
from typing import Type, Optional
from uuid import UUID

import aiohttp
from fastapi import Depends
from fastapi import Request, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.authenticator import Authenticator
from database.dbmodels.mixins.filtermixin import FilterParam
from api.settings import settings
from database.dbasync import redis, db_eager, db_unique, async_maker
from database.dbmodels.user import User
from common.messenger import Messenger
from database.dbsync import BaseMixin
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


_http_session: Optional[aiohttp.ClientSession] = None


def get_http_session():
    return _http_session


def set_http_session(http_session: aiohttp.ClientSession):
    global _http_session
    _http_session = http_session


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


class FilterQueryParamsDep:
    def __init__(self,
                 table: Type[BaseMixin],
                 model: Type[BaseModel]):
        self.table = table
        self.model = model

    def __call__(self, request: Request):
        filters = []
        for key in request.query_params.keys():
            try:
                filters.append(FilterParam.parse(key, request.query_params.getlist(key), self.table, self.model))
            except ValueError:
                continue
        return filters
