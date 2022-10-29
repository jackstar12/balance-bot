from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.dbmodels.label import LabelGroup
from api.dependencies import get_db
from api.models.user import UserRead
from database.models.user import UserPublicInfo
from api.users import CurrentUser
from api.users import get_current_user
from api.utils.responses import OK, ResponseModel, BadRequest
from database.dbasync import redis
from database.dbmodels.user import User
from database.models.user import ProfileData, UserProfile
from api.models.alert import Alert
from api.models.client import ClientInfo
from api.models.labelinfo import LabelGroupInfo
from database.models import BaseModel
from database.models.document import DocumentModel

router = APIRouter(
    tags=["transfer"],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    },
    prefix="/user"
)


@router.delete('')
async def delete_user(db: AsyncSession = Depends(get_db), user: User = Depends(CurrentUser)):
    await db.execute(
        delete(User).where(User.id == user.id)
    )
    await db.commit()

    return OK('Success')


user_info_dep = get_current_user(
    User.oauth_accounts,
    (User.label_groups, LabelGroup.labels),
    User.alerts,
    User.all_clients
)


class UserInfo(UserRead, UserPublicInfo):
    all_clients: list[ClientInfo]
    label_groups: list[LabelGroupInfo]
    alerts: list[Alert]

    class Config:
        orm_mode = True


@router.get('', response_model=ResponseModel[UserInfo])
async def info(user: User = Depends(user_info_dep),
               db: AsyncSession = Depends(get_db)):
    for account in user.oauth_accounts:
        await account.populate_oauth_data(redis=redis)

    await db.commit()

    return OK(
        result=UserInfo.from_orm(user)
    )


class UserUpdate(BaseModel):
    profile: Optional[UserProfile]
    about_me: Optional[DocumentModel]


@router.patch('', response_model=ResponseModel[UserPublicInfo])
async def update_user(body: UserUpdate,
                      user: User = Depends(user_info_dep),
                      db: AsyncSession = Depends(get_db)):

    if body.profile:
        if not body.profile['src']:
            user.info = ProfileData(
                name=body.profile['name'],
                avatar_url=body.profile['avatar_url']
            )
        elif user.get_oauth(body.profile['src']):
            user.info = body.profile['src']

    if body.about_me:
        user.about_me = body.about_me

    await db.commit()

    return OK(
        result=UserPublicInfo.from_orm(user)
    )
