from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.api.dependencies import get_db
from tradealpha.api.models.user import UserInfo
from tradealpha.api.users import CurrentUser
from tradealpha.api.users import get_current_user
from tradealpha.api.utils.responses import OK, ResponseModel
from tradealpha.common.dbasync import redis
from tradealpha.common.dbmodels import Client
from tradealpha.common.dbmodels.user import User

router = APIRouter(
    tags=["transfer"],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


@router.delete('/delete')
async def delete_user(db: AsyncSession = Depends(get_db), user: User = Depends(CurrentUser)):
    await db.execute(
        delete(User).where(User.id == user.id)
    )
    await db.commit()

    return OK('Success')


user_info_dep = get_current_user(
    User.oauth_accounts,
    User.labels,
    User.alerts,
    (
        User.all_clients, Client.events
    ),
)


@router.get('/info', response_model=ResponseModel[UserInfo])
async def info(user: User = Depends(user_info_dep),
               db: AsyncSession = Depends(get_db)):
    for account in user.oauth_accounts:
        await account.populate_oauth_data(redis=redis)

    await db.commit()

    return OK(
        result=UserInfo.from_orm(user)
    )

