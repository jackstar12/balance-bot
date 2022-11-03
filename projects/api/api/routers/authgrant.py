from datetime import datetime
from typing import Optional

from fastapi import Depends

from api.crudrouter import create_crud_router, Route
from api.dependencies import CurrentUser
from database.dbmodels import User
from database.dbsync import BaseMixin
from database.models import OrmBaseModel, OutputID, CreateableModel, BaseModel
from database.models.user import UserPublicInfo
from database.dbmodels.authgrant import (
    AuthGrant,
    GrantType,
    JournalAssociation,
    ChapterAssociation,
    EventAssociation
)

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


class AddToGrant(BaseModel):
    id: InputID


@router.patch('/{grant_id}/add/{type}')
async def add_to_grant(grant_id: int,
                       type: GrantType,
                       user: Depends(CurrentUser),
                       body: AddToGrant,
                       db: AsyncSession = Depends(get_db)):
    if type == GrantType.EVENT:
        new = EventAssociation(event_id=body.id)
    elif type == GrantType.CHAPTER:
        new = ChapterAssociation(chapter_id=body.id)
    elif type == GrantType.JOURNAL:
        new = JournalAssociation(journal_id=body.id)
    elif type == GrantType.TRADE:
        new = JournalAssociation(journal_id=body.id)
    else:
        return BadRequest(detail='Invalid Type')

    new.grant_id = grant_id
    new.user = user
    db.add(new)
    await db.commit()

    return OK()


@router.delete('/{grant_id}/remove/{type}/{id}')
async def add_to_grant(grant_id: int,
                       type: GrantType,
                       id: int,
                       user: Depends(CurrentUser),
                       body: AddToGrant,
                       db: AsyncSession = Depends(get_db)):
    if type == GrantType.EVENT:
        new = EventAssociation(event_id=body.id)
    elif type == GrantType.CHAPTER:
        new = ChapterAssociation(chapter_id=body.id)
    elif type == GrantType.JOURNAL:
        new = JournalAssociation(journal_id=body.id)
    elif type == GrantType.TRADE:
        new = JournalAssociation(journal_id=body.id)
    else:
        return BadRequest(detail='Invalid Type')

    new.grant_id = grant_id
    new.user = user
    db.add(new)
    await db.commit()

    return OK()
