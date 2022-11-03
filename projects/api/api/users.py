import os
import uuid
from operator import and_, or_
from typing import Optional, Generic, Type

from fastapi import Depends, APIRouter, HTTPException
from fastapi.security import APIKeyQuery
from fastapi_users import FastAPIUsers, schemas, BaseUserManager, models, exceptions
from fastapi_users.authentication import (
    CookieTransport,
    AuthenticationBackend, Transport, Strategy
)
from fastapi_users.jwt import SecretType
from fastapi_users.models import ID, UOAP, OAP
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from httpx_oauth.oauth2 import BaseOAuth2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from starlette.requests import Request

from api.authenticator import RedisStrategy
from api.dependencies import get_db
from api.oauth import get_oauth_router
from api.settings import settings
from api.usermanager import UserManager
from core import utc_now
from database.dbasync import redis, db_eager, db_unique, safe_op, TEager
from database.dbmodels.authgrant import AuthGrant, GrantAssociaton
from database.dbmodels.user import User, OAuthAccount


class UserDatabase(Generic[ID, OAP], SQLAlchemyUserDatabase[User, ID]):
    def __init__(self, *args, base_stmt: Select, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_stmt = base_stmt

    async def get_by_token(self, token: str):
        return await self._get_user(
            self.base_stmt.join(
                AuthGrant, and_(
                    AuthGrant.user_id == User.id,
                    AuthGrant.token == token
                )
            )
        )

    async def get(self, id: ID) -> Optional[UOAP]:
        statement = self.base_stmt.filter(self.user_table.id == id)
        return await self._get_user(statement)

    async def delete_oauth_account(self, user: UOAP, oauth_name: str):
        for oauth_account in user.oauth_accounts:
            if oauth_account.oauth_name == oauth_name:
                await self.session.delete(oauth_account)
                await self.session.commit()


class UserDatabaseDep:

    def __init__(self, *eager):
        self.base_stmt = db_eager(select(User), *eager)
        self._eager_loads = eager

    async def __call__(self, db: AsyncSession = Depends(get_db)):
        yield UserDatabase(base_stmt=self.base_stmt, session=db, user_table=User, oauth_account_table=OAuthAccount)


class CustomFastAPIUsers(FastAPIUsers[User, uuid.UUID]):
    def get_custom_oauth_router(
            self,
            oauth_client: BaseOAuth2,
            backend: AuthenticationBackend,
            user_schema: schemas.BaseOAuthAccount,
            state_secret: SecretType,
            redirect_url: str = None,
    ) -> APIRouter:
        """
        Return an OAuth router for a given OAuth client and authentication backend.

        :param user_schema:
        :param oauth_client: The HTTPX OAuth client instance.
        :param backend: The authentication backend instance.
        :param state_secret: Secret used to encode the state JWT.
        :param redirect_url: Optional arbitrary redirect URL for the OAuth2 flow.
        If not given, the URL to the callback endpoint will be generated.
        """
        return get_oauth_router(
            oauth_client,
            backend,
            user_schema,
            self.authenticator,
            self.get_user_manager,
            state_secret,
            redirect_url,
        )


get_user_db = UserDatabaseDep(User.oauth_accounts)


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    yield UserManager(user_db)


def get_redis_strategy():
    return RedisStrategy(redis=redis, lifetime_seconds=48 * 60 * 60)


OAUTH2_REDIRECT_URI = os.environ.get('REDIRECT_BASE_URI')

assert OAUTH2_REDIRECT_URI


# class CustomTransport(CookieTransport):
#     def get_login_response(self, token: str, response: Response) -> Any:
#         resp = RedirectResponse(url=)
#
#         super().get_login_response(token, response)
#         response.st


class TokenTransport(Transport):
    scheme: APIKeyQuery

    def __init__(self):
        self.scheme = APIKeyQuery(
            name="token",
            auto_error=False
        )


class UserTransport(Transport):
    scheme: APIKeyQuery

    def __init__(self):
        self.scheme = APIKeyQuery(
            name="user",
            auto_error=False
        )


class TokenStrategy(Strategy[User, uuid.UUID]):
    def __init__(self,
                 grant: AuthGrant):
        self.grant = grant

    async def read_token(
            self, token: Optional[str], user_manager: BaseUserManager[User, models.ID]
    ) -> Optional[User]:
        if self.grant is None:
            return None
        try:
            return await user_manager.get(self.grant.user_id)
        except (exceptions.UserNotExists, exceptions.InvalidID):
            return None


token_transport = TokenTransport()
user_transport = UserTransport()

auth_backend = AuthenticationBackend(
    name="cookie",
    transport=CookieTransport(
        settings.session_cookie_name,
        cookie_secure=False,
        cookie_max_age=settings.session_cookie_max_age
    ),
    get_strategy=get_redis_strategy
)


def get_auth_grant_dependency(*eager: list[TEager],
                              association_table: Type[GrantAssociaton] = None):
    async def get_auth_grant(request: Request,
                             db: AsyncSession = Depends(get_db),
                             user: Optional[User] = Depends(OptionalUser),
                             token=Depends(token_transport.scheme),
                             public_user_id=Depends(user_transport.scheme)):
        now = utc_now()

        base = select(AuthGrant).where(
            or_(
                AuthGrant.expires < now,
                AuthGrant.expires == None
            )
        )

        if token:
            base = base.where(
                AuthGrant.token == token,
            )
        elif public_user_id:
            base = base.where(
                AuthGrant.user_id == public_user_id,
                AuthGrant.public == True
            )
        elif not user:
            raise HTTPException(status_code=401, detail='Unauthorized')

        if association_table:
            add = [
                int(value) == getattr(association_table, name)
                for name, value in request.path_params.items()
                if hasattr(association_table, name)
            ]
            if add and False:
                base = base.join(
                    association_table,
                    and_(
                        AuthGrant.id == association_table.grant_id,
                        *add
                    )
                )

        grant: AuthGrant = await db_unique(
            base,
            *eager,
            session=db,
        )

        if not grant and not user:
            raise HTTPException(status_code=401, detail='Unauthorized')

        try:
            if grant:
                await grant.validate(user)
            return grant
        except AssertionError:
            return None

    return get_auth_grant


def get_token_backend(association_table: Type[GrantAssociaton]):
    def get_token_strategy(grant: AuthGrant = Depends(get_auth_grant_dependency(association_table=association_table))):
        return TokenStrategy(grant=grant)

    return AuthenticationBackend(
        name=association_table.__tablename__,
        transport=token_transport,
        get_strategy=get_token_strategy
    )

    return AuthenticationBackend(
        name=association_table.__tablename__,
        transport=token_transport,
        get_strategy=get_token_strategy
    )


def get_current_user(*eager, auth_backends: list[AuthenticationBackend] = None, optional=False):
    _get_user_db = UserDatabaseDep(*eager)

    def _get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(_get_user_db)):
        yield UserManager(user_db)

    users = FastAPIUsers[User, uuid.UUID](
        _get_user_manager,
        auth_backends=[*auth_backends, auth_backend] if auth_backends else [auth_backend]
    )

    return users.authenticator.current_user(optional=optional)


fastapi_users = CustomFastAPIUsers(
    get_user_manager,
    auth_backends=[auth_backend]
)

CurrentUser = fastapi_users.current_user(optional=False, active=True)
OptionalUser = fastapi_users.current_user(optional=True, active=True)
