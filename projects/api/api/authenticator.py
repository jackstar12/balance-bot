import secrets
from http import HTTPStatus
from typing import Optional, Generic

import aioredis
from aioredis import Redis
from fastapi import Response, Request, HTTPException
from fastapi_users import models, BaseUserManager, exceptions
from fastapi_users.authentication import Strategy
from pydantic import UUID4

from api.settings import settings
from database.dbmodels.user import User


class Authenticator:

    def __init__(self, redis: Redis, session_expiration: int, session_cookie_name = None):
        self.redis = redis
        self.session_expiration = session_expiration
        self.session_cookie_name = session_cookie_name or settings.session_cookie_name

    def _get_session_id(self, request: Request):
        session_id = request.cookies.get(self.session_cookie_name)
        if session_id is None:
            raise HTTPException(
                status_code=HTTPStatus.UNAUTHORIZED,
                detail='Missing session cookie'
            )
        return session_id

    async def verify_id(
        self, request: Request,
    ) -> Optional[UUID4]:
        session_id = self._get_session_id(request)
        user_id = await self.redis.get(session_id)
        if user_id is None:
            raise HTTPException(
                status_code=HTTPStatus.UNAUTHORIZED,
                detail='Invalid session'
            )

        return UUID4(user_id.decode('utf-8'))

    async def write_token(self, user: User) -> str:
        token = secrets.token_urlsafe()
        await self.redis.sadd(f'sessions:{user.id}', token)
        await self.redis.set(token, str(user.id), ex=self.session_expiration)
        return token

    async def destroy_token(self, token: str) -> None:
        await self.redis.delete(token)

    async def set_session_cookie(self, response: Response, user: User):
        response.set_cookie(
            self.session_cookie_name,
            value=await self.write_token(user)
        )

    def unset_session_cooke(self, response: Response):
        response.delete_cookie(self.session_cookie_name)

    async def invalidate_user_sessions(self, user: User):
        await self.redis.delete(f'sessions:{user.id}')

    async def invalidate_session(self, request: Request):
        session_id = self._get_session_id(request)
        await self.redis.delete(session_id)


class RedisStrategy(Strategy[models.UP, models.ID], Generic[models.UP, models.ID]):
    def __init__(self, redis: aioredis.Redis, lifetime_seconds: Optional[int] = None):
        self.redis = redis
        self.lifetime_seconds = lifetime_seconds

    async def read_token(
        self, token: Optional[str], user_manager: BaseUserManager[models.UP, models.ID]
    ) -> Optional[models.UP]:
        if token is None:
            return None

        user_id = await self.redis.get(token)
        if user_id is None:
            return None

        try:
            parsed_id = user_manager.parse_id(user_id.decode('utf-8'))
            return await user_manager.get(parsed_id)
        except (exceptions.UserNotExists, exceptions.InvalidID):
            return None

    async def write_token(self, user: models.UP) -> str:
        token = secrets.token_urlsafe()
        await self.redis.set(token, str(user.id), ex=self.lifetime_seconds)
        return token

    async def destroy_token(self, token: str, user: models.UP) -> None:
        await self.redis.delete(token)

