import asyncio
import logging
from http import HTTPStatus
from typing import Type
from uuid import UUID

from fastapi import Request, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.api.models.FilterParam import FilterParam
from tradealpha.common.models import BaseModel
from tradealpha.api.authenticator import Authenticator
from tradealpha.common.dbasync import redis, db_eager, db_unique, async_maker
from tradealpha.api.settings import settings
from fastapi import Depends
from tradealpha.common.dbmodels.user import User
from tradealpha.common.messenger import Messenger

default_authenticator = Authenticator(
    redis,
    session_expiration=48 * 60 * 60,
    session_cookie_name=settings.session_cookie_name
)

messenger = Messenger(redis)


def get_authenticator() -> Authenticator:
    return default_authenticator


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
        self.base_stmt = db_eager(select(User), *eager_loads)

    async def __call__(self,
                       request: Request,
                       authenticator = Depends(get_authenticator),
                       db: AsyncSession = Depends(get_db)):
        uuid = await authenticator.verify_id(request)
        user = await db_unique(self.base_stmt.filter_by(id=uuid), session=db) if uuid else None
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






