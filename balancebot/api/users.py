import uuid
from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    RedisStrategy,
)
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from balancebot.api.authenticator import Authenticator
from balancebot.common.dbmodels.user import User as UserTable, User
from balancebot.common.dbasync import async_session
from balancebot.api.models.user import UserCreate

SECRET = "SECRET"


async def get_user_db():
    yield SQLAlchemyUserDatabase(async_session, UserTable)


class UserManager(UUIDIDMixin, BaseUserManager[UserCreate, uuid.UUID]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(self, user: User, request: Optional[Request] = None):
        print(f"User {user.id} has registered.")

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None, authenticator = Depends(Authenticator)
    ):
        await authenticator.invalidate_user_sessions(user)
        print(f"User {user.id} has forgot their password. Reset token: {token}")

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None, authenticator = Depends(Authenticator)
    ):
        await authenticator.invalidate_user_sessions(user)
        print(f"Verification requested for user {user.id}. Verification token: {token}")


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    yield UserManager(user_db)


fastapi_users = FastAPIUsers(
    get_user_manager,
    []
)
