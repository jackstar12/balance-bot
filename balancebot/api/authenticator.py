import secrets
from http import HTTPStatus
from typing import Optional, Union

from fastapi import Response, Request, HTTPException
from aioredis import Redis
from pydantic import UUID4

from balancebot.common.dbmodels.user import User
from balancebot.api.models.user import UserDB
from balancebot.api.settings import settings


class Authenticator:

    def __init__(self, redis: Redis, session_expiration: int, session_cookie_name = None):
        self.redis = redis
        self.session_expiration = session_expiration
        self.session_cookie_name = session_cookie_name or settings.session_cookie_name

    def _get_session_id(self, request: Request):
        session_id = request.cookies.get(self.session_cookie_name)
        if session_id is None:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail='Missing session cookie'
            )
        return session_id

    async def read_uuid(
        self, request: Request,
    ) -> Optional[UUID4]:
        session_id = self._get_session_id(request)
        user_id = await self.redis.get(session_id)
        if user_id is None:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail='Invalid session'
            )

        return UUID4(user_id.decode('utf-8'))

    async def write_token(self, user: Union[User, UserDB]) -> str:
        token = secrets.token_urlsafe()
        await self.redis.sadd(f'sessions:{user.id}', token)
        await self.redis.set(token, str(user.id), ex=self.session_expiration)
        return token

    async def destroy_token(self, token: str) -> None:
        await self.redis.delete(token)

    async def set_session_cookie(self, response: Response, user: Union[User, UserDB]):
        response.set_cookie(
            self.session_cookie_name,
            value=await self.write_token(user)
        )

    def unset_session_cooke(self, response: Response):
        response.delete_cookie(self.session_cookie_name)

    async def invalidate_user_sessions(self, user: Union[User, UserDB]):
        await self.redis.delete(f'sessions:{user.id}')

    async def invalidate_session(self, request: Request):
        session_id = self._get_session_id(request)
        await self.redis.delete(session_id)
