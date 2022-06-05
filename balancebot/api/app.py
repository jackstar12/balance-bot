from datetime import datetime

import pytz
import uvicorn
import asyncio
import aiohttp

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from fastapi import Depends
from fastapi import FastAPI
from starlette_csrf import CSRFMiddleware

import balancebot.common.database_async as aio_db
from balancebot.api.db_session_middleware import DbSessionMiddleware
from balancebot.common.dbmodels.trade import Trade

from balancebot.common.dbmodels.user import User
from balancebot.api.dependencies import CurrentUser, CurrentUserDep
from balancebot.api.models.user import UserInfo, UserRead, UserCreate
from balancebot.api.settings import settings
from balancebot.common.database import Base, engine

import balancebot.api.routers.authentication as auth
import balancebot.api.routers.client as client
import balancebot.api.routers.label as label
import balancebot.api.routers.analytics as analytics
import balancebot.api.routers.journal as journal
from balancebot.common.dbmodels.discorduser import DiscordUser
from balancebot.common.dbmodels.guild import Guild
import balancebot.api.routers.discordauth as discord

from balancebot.api.users import fastapi_users
from balancebot.common.enums import Tier

app = FastAPI(
    docs_url='/api/v1/docs',
    openapi_url='/api/v1/openapi.json',
    title="ChimichangApp",
    description='yoyo',
    version="0.0.1",
    terms_of_service="http://example.com/terms/",
    contact={
        "name": "Deadpoolio the Amazing",
        "url": "http://x-force.example.com/contact/",
        "email": "dp@x-force.example.com",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
)

# app.add_middleware(SessionMiddleware, secret_key='SECRET')
app.add_middleware(CSRFMiddleware, secret='SECRET', sensitive_cookies=[settings.session_cookie_name])
app.add_middleware(DbSessionMiddleware)

app.include_router(fastapi_users.get_verify_router(UserRead), prefix='/api/v1')
app.include_router(fastapi_users.get_reset_password_router(), prefix='/api/v1')
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix='/api/v1')

for module in (discord, auth, client, label, analytics, journal):
    app.include_router(module.router, prefix='/api/v1')

Base.metadata.create_all(bind=engine)


@app.post('/delete')
async def delete_user(user: User = Depends(CurrentUser)):
    await aio_db.db_del_filter(User, id=user.id)
    await aio_db.async_session.commit()

    return {'msg': 'Success'}


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


@app.get('/api/v1/info', response_model=UserInfo)
async def info(user: User = Depends(user_info)):
    return UserInfo.from_orm(user)
    # as_dict = user.__dict__
    # as_dict['clients'] = [client.__dict__ for client in user.all_clients]
    # jsonable_encoder
    # return JSONResponse(dict(
    #    clients=[
    #        dict(
    #
    #        )
    #    ]
    # ))
    #
    # return UserInfo.construct(**as_dict)
    # This generates a UserInfo model, however, for performance reasons, it's not converted to one.

    # stmt = aio_db.db_eager(select(User),
    #                       (User.clients, Client.trades),
    #                       (User.clients, Client.events),
    #                       User.alerts,
    #                       User.labels,
    #                       (User.discord_user, [(DiscordUser.clients, Client.events)]),
    #                       (User.discord_user, [(DiscordUser.clients, Client.trades)]),
    #                       )

    # test2 = await aio_db.db_unique(stmt)
    #
    # stmt2 = Client.construct_load_options(full=False, data=True)
    # test2 = await aio_db.db_unique(stmt2)
    # stmt3 = Client.construct_load_options(full=True, data=False)
    # test = await aio_db.db_unique(stmt3)

# apiutils.create_endpoint(
#    route='/api/v1/client',
#    methods={
#        'POST': {
#            'args': [
#                ("exchange", True),
#                ("api_key", True),
#                ("api_secret", True),
#                ("subaccount", False),
#                ("extra_kwargs", False)
#            ],
#            'callback': register_client
#        },
#        'GET': {
#            'args': [
#                ("id", False),
#                ("currency", False),
#                ("since", False),
#                ("to", False),
#            ],
#            'callback': get_client
#        },
#        'DELETE': {
#            'args': [
#                ("id", True)
#            ],
#            'callback': delete_client
#        }
#    },
#    jwt_auth=True
# )


# apiutils.create_endpoint(
#    route='/api/v1/label',
#    methods={
#        'POST': {
#            'args': [
#                ("name", True),
#                ("color", True)
#            ],
#            'callback': create_label
#        },
#        'PATCH': {
#            'args': [
#                ("id", True),
#                ("name", False),
#                ("color", False)
#            ],
#            'callback': update_label
#        },
#        'DELETE': {
#            'args': [
#                ("id", True),
#            ],
#            'callback': delete_label
#        }
#    },
#    jwt_auth=True
# )


# apiutils.create_endpoint(
#    route='/api/v1/label/trade',
#    methods={
#        'POST': {
#            'args': [
#                ("client_id", True),
#                ("trade_id", True),
#                ("label_id", True)
#            ],
#            'callback': add_label
#        },
#        'DELETE': {
#            'args': [
#                ("client_id", True),
#                ("trade_id", True),
#                ("label_id", True)
#            ],
#            'callback': remove_label
#        },
#        'PATCH': {
#            'args': [
#                ("client_id", True),
#                ("trade_id", True),
#                ("label_ids", True)
#            ],
#            'callback': set_labels
#        }
#    },
#    jwt_auth=True
# )


@app.on_event("startup")
async def on_start():
    async with aio_db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)



async def db_test():
    async with aio_db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

def run():
    uvicorn.run(app, host='localhost', port=5000)


if __name__ == '__main__':
    run()
