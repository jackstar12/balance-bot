from datetime import datetime
from enum import Enum
from operator import and_
from typing import Optional, Type

from fastapi import Depends
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.crudrouter import create_crud_router, Route
from api.dependencies import get_db
from api.users import CurrentUser
from api.utils.responses import BadRequest, OK
from database.dbmodels import User
from database.dbsync import BaseMixin
from database.models import OrmBaseModel, OutputID, CreateableModel, BaseModel
from database.models.user import UserPublicInfo

from database.dbmodels.authgrant import (
    AuthGrant,
    JournalGrant,
    ChapterGrant,
    EventGrant,
    TradeGrant,
    GrantAssociaton
)
from database.redis import TableNames

from lib.database.database.models import InputID


class AuthGrantInfo(OrmBaseModel):
    id: OutputID
    owner: UserPublicInfo
    expires: Optional[datetime]
    token: Optional[str]
    public: Optional[bool]
    data: Optional[dict]


class AuthGrantCreate(CreateableModel):
    expires: Optional[datetime]
    public: Optional[datetime]

    def get(self, user: User) -> BaseMixin:
        return AuthGrant(**self.dict(), user=user)


router = create_crud_router('/auth-grant',
                            table=AuthGrant,
                            read_schema=AuthGrantInfo,
                            create_schema=AuthGrantCreate,
                            default_route=Route(
                                eager_loads=[AuthGrant.user]
                            ))


class GrantType(Enum):
    EVENT = 'event'
    CHAPTER = 'chapter'
    TRADE = 'trade'
    JOURNAL = 'journal'

    def get_impl(self) -> Type[GrantAssociaton]:
        if self == GrantType.EVENT:
            return EventGrant
        elif self == GrantType.CHAPTER:
            return ChapterGrant
        elif self == GrantType.JOURNAL:
            return JournalGrant
        elif self == GrantType.TRADE:
            return TradeGrant


class AddToGrant(BaseModel):
    pass
    #id: InputID


@router.post('/{grant_id}/permit/{type}/{id}')
async def add_to_grant(grant_id: int,
                       type: GrantType,
                       id: int,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    impl = type.get_impl()
    if not impl:
        return BadRequest(detail='Invalid Type')
    instance = impl()

    instance.grant_id = grant_id
    instance.user = user
    instance.identity = id

    try:
        db.add(instance)
        await db.commit()
    except IntegrityError as e:
        return BadRequest(f'Invalid grant or {type.value} id')

    return OK()


@router.delete('/{grant_id}/permit/{type}/{id}')
async def add_to_grant(grant_id: int,
                       type: GrantType,
                       id: int,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    impl = type.get_impl()
    if not impl:
        return BadRequest(detail='Invalid Type')
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
        return BadRequest(f'Invalid grant or {type.value} id')
