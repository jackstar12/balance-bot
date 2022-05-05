from http import HTTPStatus

from fastapi import Request, HTTPException
from sqlalchemy import select

from balancebot.api.authenticator import Authenticator
from balancebot.common.database_async import redis, db_eager, db_unique
from balancebot.api.settings import settings
from fastapi import Depends
from balancebot.common.dbmodels.user import User


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
        if not user:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail='Invalid session'
            )
        return user


current_user = CurrentUser()
