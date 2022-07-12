import asyncio
import logging
from http import HTTPStatus

from fastapi import Request, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.api.authenticator import Authenticator
from tradealpha.common.dbasync import redis, db_eager, db_unique, async_maker
from tradealpha.api.settings import settings
from fastapi import Depends
from tradealpha.common.dbmodels.user import User
from tradealpha.common.messenger import Messenger

authenticator = Authenticator(
    redis,
    session_expiration=48 * 60 * 60,
    session_cookie_name=settings.session_cookie_name
)

messenger = Messenger(redis)


def get_authenticator() -> Authenticator:
    return authenticator


async def get_user_id(request: Request, authenticator = Depends(get_authenticator)):
    return await authenticator.verify_id(request)


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





