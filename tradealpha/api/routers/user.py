from fastapi import APIRouter, Depends, Body

from tradealpha.api.utils.responses import OK
from tradealpha.api.models.user import UserInfo
from tradealpha.common.dbmodels.discorduser import DiscordUser
from tradealpha.common.dbmodels.guild import Guild
from tradealpha.api.dependencies import CurrentUser, get_messenger, get_db, CurrentUserDep
from tradealpha.common.dbmodels.user import User
import tradealpha.common.dbasync as aio_db

router = APIRouter(
    tags=["transfer"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


@router.delete('/delete')
async def delete_user(user: User = Depends(CurrentUser)):
    await aio_db.db_del_filter(User, id=user.id)
    await aio_db.async_session.commit()

    return OK('Success')


user_info = CurrentUserDep(
    (
        User.discord_user, [
            DiscordUser.global_associations,
            (DiscordUser.guilds, Guild.events)
        ]
    ),
    User.all_clients,
    User.labels,
    User.alerts
)


@router.get('/info', response_model=UserInfo)
async def info(user: User = Depends(user_info)):
    return UserInfo.from_orm(user)
