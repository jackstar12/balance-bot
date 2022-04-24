from datetime import datetime

import pytz
import uvicorn
import asyncio
import aiohttp

from fastapi_jwt_auth.exceptions import AuthJWTException
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, noload, selectinload, lazyload
from sqlalchemy.sql import Select
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse

from fastapi import Depends
from fastapi_jwt_auth import AuthJWT
from fastapi import FastAPI, Request
from starlette_csrf import CSRFMiddleware

import balancebot.api.database_async as aio_db
from balancebot.api.dbmodels.trade import Trade

from balancebot.api.dbmodels.user import User
from balancebot.api.dependencies import current_user, CurrentUser
from balancebot.api.settings import settings
from balancebot.api.database import Base, engine, session, redis

import balancebot.api.routers.authentication as auth
import balancebot.api.routers.client as client
import balancebot.api.routers.label as label
from balancebot.api.dbmodels.discorduser import DiscordUser
from balancebot.api.dbmodels.guild import Guild
from balancebot.api.dbmodels.balance import Balance
import balancebot.api.routers.discordauth as discord

import balancebot.collector.collector as collector
from balancebot.api.users import fastapi_users
from balancebot.api.utils.responses import OK
from balancebot.common.enums import Tier
from balancebot.common.messenger import Messenger

app = FastAPI(
    root_path='/api/v1'
)

# app.add_middleware(SessionMiddleware, secret_key='SECRET')
app.add_middleware(CSRFMiddleware, secret='SECRET', sensitive_cookies=[settings.session_cookie_name])

app.include_router(fastapi_users.get_verify_router(), prefix='/api/v1')
app.include_router(fastapi_users.get_reset_password_router(), prefix='/api/v1')
app.include_router(fastapi_users.get_register_router(), prefix='/api/v1')

app.include_router(discord.router, prefix='/api/v1')
app.include_router(auth.router, prefix='/api/v1')
app.include_router(client.router, prefix='/api/v1')
app.include_router(label.router, prefix='/api/v1')

Base.metadata.create_all(bind=engine)


@AuthJWT.load_config
def get_config():
    return settings


@AuthJWT.token_in_denylist_loader
async def token_in_denylist(decoded_token):
    result = await redis.get(decoded_token)
    return result and result == ''


# exception handler for authjwt
# in production, you can tweak performance using orjson response
@app.exception_handler(AuthJWTException)
def authjwt_exception_handler(request: Request, exc: AuthJWTException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message}
    )


@app.post('/delete')
async def delete_user(user: User = Depends(current_user)):
    await aio_db.db_del_filter(User, id=user.id)
    await aio_db.async_session.commit()
    return {'msg': 'Success'}


@app.get('/api/v1/info')
async def info():

    user = session.query(User).options(lazyload('*')).first()

    return await user.serialize(full=True, data=False)

    stmt = User.construct_load_options(full=True, data=False)
    from balancebot.api.dbmodels.client import Client

    test = await aio_db.db_unique(stmt)

    stmt = aio_db.db_eager(select(User),
                           (User.clients, Client.trades),
                           (User.clients, Client.events),
                           User.alerts,
                           User.labels,
                           (User.discorduser, [(DiscordUser.clients, Client.events)]),
                           (User.discorduser, [(DiscordUser.clients, Client.trades)]),
                           )

    #test2 = await aio_db.db_unique(stmt)
#
    #stmt2 = Client.construct_load_options(full=False, data=True)
    #test2 = await aio_db.db_unique(stmt2)
    #stmt3 = Client.construct_load_options(full=True, data=False)
    #test = await aio_db.db_unique(stmt3)
    return await test.serialize(full=True, data=False)


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
    from balancebot.bot import bot
    from balancebot.api.dbmodels.client import Client
    from balancebot.api.dbmodels.event import Event
    p = Event.registrations

    event = await aio_db.db_unique(select(Event), Event.registrations)

    c = Client.events
    stmt2 = select(User).options(
            selectinload(User.clients).selectinload(Client.trades)
        ).options(
            selectinload(User.alerts)
        ).options(
            selectinload(User.discorduser).selectinload(DiscordUser.clients).selectinload(Client.trades).selectinload(Trade.executions)
        )

    print(len(str(stmt2)))

    test2 = await aio_db.db_unique(
        stmt2
    )
    stmt = aio_db.db_eager(select(User),
                           (User.clients, [Client.trades, Client.events]),
                           User.alerts,
                           (User.discorduser, (DiscordUser.clients, (Client.trades, Trade.executions)))
                           )

    res = await aio_db.db_unique(stmt)

    async def run_all():
        async with aiohttp.ClientSession() as http_session:
            await asyncio.gather(
                bot.run(http_session),
                collector.run(http_session)
            )
            print('done')

    asyncio.create_task(run_all())


async def db_test():
    async with aio_db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from balancebot.api.dbmodels.client import Client
    from balancebot.api.dbmodels.balance import Balance

    sess = aio_db.async_session

    users = await aio_db.db_all(select(User))
    guilds = await aio_db.db_all(select(Guild))
    guild = await aio_db.db_first(select(Guild))

    result = await sess.execute(
        delete(Guild).filter_by(id=234)
    )
    now = datetime.now(tz=pytz.UTC)
    client = await sess.get(Client, 53)
    history = await aio_db.db_all(client.history.statement.filter(
        Balance.time < now
    ))

    sess.add(Guild(
        id=23456,
        name='hs',
        tier=Tier.PREMIUM
    ))

    try:
        await sess.commit()
    except IntegrityError:
        pass


def run():
    uvicorn.run(app, host='localhost', port=5000)


if __name__ == '__main__':
    run()
