from datetime import datetime
from enum import Enum
from operator import and_
from typing import Optional, Type, Literal

from fastapi import Depends, APIRouter
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.crudrouter import add_crud_routes, Route
from api.dependencies import get_db
from api.users import CurrentUser, DefaultGrant
from api.utils.responses import BadRequest, OK, Unauthorized
from database.dbasync import wrap_greenlet, db_unique
from database.dbmodels import User
from database.models import OrmBaseModel, OutputID, CreateableModel, BaseModel
from database.models.user import UserPublicInfo

from database.dbmodels.authgrant import (
    AuthGrant,
    DiscordPermission,
    AssociationType
)

from database.models import InputID


class AuthGrantCreate(CreateableModel):
    expires: Optional[datetime]
    public: Optional[bool]
    discord: Optional[DiscordPermission]
    token: Optional[bool]
    wildcards: Optional[list[AssociationType]]
    name: Optional[str]

    def dict(
            self,
            *,
            exclude_none=False,
            **kwargs
    ):
        return super().dict(exclude_none=False, **kwargs)

    def get(self, user: User) -> AuthGrant:
        return AuthGrant(**self.dict(), user=user)


class AuthGrantInfo(AuthGrantCreate, OrmBaseModel):
    id: OutputID
    owner: UserPublicInfo
    token: Optional[str]



router = APIRouter(
    tags=["Auth Grant"],
    prefix="/auth-grant"
)


class AddToGrant(BaseModel):
    pass
    # id: InputID


@router.get('/current', response_model=AuthGrantInfo)
@wrap_greenlet
def get_current_grant(grant: AuthGrant = Depends(DefaultGrant)):
    return OK(result=AuthGrantInfo.from_orm(grant))


@router.post('/{grant_id}/permit/{type}/{id}')
async def add_to_grant(grant_id: InputID,
                       type: AssociationType,
                       id: InputID,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):

    # Verify grant id
    grant_id = await db_unique(
        select(AuthGrant.id).where(
            AuthGrant.id == grant_id,
            AuthGrant.user_id == user.id
        )
    )

    if not grant_id:
        raise Unauthorized('Can not access this grant')

    impl = type.get_impl()
    if not impl:
        raise BadRequest(detail='Invalid Type')
    instance = impl()

    instance.grant_id = grant_id
    instance.user = user
    instance.identity = id

    try:
        db.add(instance)
        await db.commit()
    except IntegrityError:
        raise BadRequest(f'Invalid grant or {type.value} id')

    return OK()


@router.delete('/{grant_id}/permit/{type}/{id}')
async def add_to_grant(grant_id: InputID,
                       type: AssociationType,
                       id: InputID,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    impl = type.get_impl()
    if not impl:
        raise BadRequest(detail='Invalid Type')
    stmt = delete(impl).where(
        impl.identity == id,
        impl.grant_id == grant_id,
        AuthGrant.id == grant_id,
        AuthGrant.user_id == user.id
    ).execution_options(
        synchronize_session=False
    )
    result = await db.execute(
        stmt
    )
    await db.commit()

    if result.rowcount == 1:
        return OK()
    else:
        raise BadRequest(f'Invalid grant or {type.value} id')


add_crud_routes(router,
                table=AuthGrant,
                read_schema=AuthGrantInfo,
                create_schema=AuthGrantCreate,
                default_route=Route(
                    eager_loads=[AuthGrant.user]
                ))
