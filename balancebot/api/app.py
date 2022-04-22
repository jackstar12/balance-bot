from datetime import datetime

import pytz
import uvicorn
import asyncio
import aiohttp

from fastapi_jwt_auth.exceptions import AuthJWTException
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Select
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse

from fastapi import Depends
from fastapi_jwt_auth import AuthJWT
from fastapi import FastAPI, Request

import balancebot.api.database_async as aio_db

from balancebot.api.dbmodels.user import User
from balancebot.api.dependencies import current_user
from balancebot.api.settings import settings
from balancebot.api.database import Base, engine, session

import balancebot.api.routers.authentication as auth
import balancebot.api.routers.client as client
import balancebot.api.routers.label as label
from balancebot.api.dbmodels.discorduser import DiscordUser
from balancebot.api.dbmodels.guild import Guild
from balancebot.api.dbmodels.balance import Balance
import balancebot.api.routers.discordauth as discord

import balancebot.collector.collector as collector
from balancebot.common.enums import Tier

app = FastAPI(
    root_path='/api/v1'
)

app.add_middleware(SessionMiddleware, secret_key='SECRET')
app.include_router(discord.router, prefix='/api/v1')
app.include_router(auth.router, prefix='/api/v1')
app.include_router(client.router, prefix='/api/v1')
app.include_router(label.router, prefix='/api/v1')

Base.metadata.create_all(bind=engine)


@AuthJWT.load_config
def get_config():
    return settings


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
def info(user: User = Depends(current_user)):
    return user.serialize(full=True, data=False)


@app.post('/refresh')
def refresh(Authorize: AuthJWT = Depends(), user: User = Depends(current_user)):
    Authorize.jwt_refresh_token_required()
    new_access_token = Authorize.create_access_token(subject=user.id)
    Authorize.set_access_cookies(new_access_token)
    return {"msg": "The token has been refreshed"}


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

    await db_test()
    from balancebot.bot import bot

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
