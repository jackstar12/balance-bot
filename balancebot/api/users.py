from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers
from fastapi_users.authentication import (
    RedisStrategy,
)
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from balancebot.api.authenticator import Authenticator
from balancebot.common.dbmodels.user import User as UserTable
from balancebot.common.database_async import async_session
from balancebot.api.models.user import User, UserCreate, UserDB, UserUpdate

SECRET = "SECRET"


async def get_user_db():
    yield SQLAlchemyUserDatabase(UserDB, async_session, UserTable)


class UserManager(BaseUserManager[UserCreate, UserDB]):
    user_db_model = UserDB
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(self, user: UserDB, request: Optional[Request] = None):
        print(f"User {user.id} has registered.")

    async def on_after_forgot_password(
        self, user: UserDB, token: str, request: Optional[Request] = None, authenticator = Depends(Authenticator)
    ):
        await authenticator.invalidate_user_sessions(user)
        print(f"User {user.id} has forgot their password. Reset token: {token}")

    async def on_after_request_verify(
        self, user: UserDB, token: str, request: Optional[Request] = None, authenticator = Depends(Authenticator)
    ):
        await authenticator.invalidate_user_sessions(user)
        print(f"Verification requested for user {user.id}. Verification token: {token}")


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    yield UserManager(user_db)

RedisStrategy


fastapi_users = FastAPIUsers(
    get_user_manager,
    [],
    User,
    UserCreate,
    UserUpdate,
    UserDB,
)
