from http import HTTPStatus

from fastapi import Depends, Request, HTTPException
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from balancebot.api.authenticator import Authenticator
from balancebot.api.database_async import db_first, redis, db_eager, db_unique
from balancebot.api.settings import settings
from balancebot.api.database import session
from fastapi import Depends
from fastapi_jwt_auth import AuthJWT
from balancebot.api.dbmodels.user import User


authenticator = Authenticator(
    redis,
    session_expiration=48 * 60 * 60,
    session_cookie_name=settings.session_cookie_name
)


def get_authenticator():
    return authenticator


class CurrentUser:
    def __init__(self, *eager_loads):
        self.base_stmt = db_eager(select(User), *eager_loads)

    async def __call__(self, request: Request, authenticator = Depends(get_authenticator)):
        uuid = await authenticator.read_uuid(request)
        user = await db_unique(self.base_stmt.filter_by(id=uuid)) if uuid else None
        user.discorduser.user = user
        if not user:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail='Invalid session'
            )
        return user


current_user = CurrentUser()
