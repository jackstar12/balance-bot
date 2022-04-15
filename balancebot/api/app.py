import uvicorn
import asyncio
import aiohttp

from fastapi_jwt_auth.exceptions import AuthJWTException
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse

from fastapi import Depends
from fastapi_jwt_auth import AuthJWT
from fastapi import FastAPI, Request

from balancebot.api.database import session

from balancebot.api.dbmodels.user import User
from balancebot.api.dependencies import current_user
from balancebot.api.settings import settings
from balancebot.api.database import Base, engine

import balancebot.api.routers.discordauth as discord
import balancebot.api.routers.authentication as auth
import balancebot.api.routers.client as client
import balancebot.api.routers.label as label
from balancebot.api.dbmodels.guild import Guild

import balancebot.collector.collector as collector

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
def delete(user: User = Depends(current_user)):
    session.query(User).filter_by(id=user.id).delete()
    session.commit()
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
def on_start():
    from balancebot.bot import bot

    async def run_all():
        async with aiohttp.ClientSession() as http_session:
            await asyncio.gather(
                bot.run(http_session),
                collector.run(http_session)
            )
            print('done')

    asyncio.create_task(run_all())


if __name__ == '__main__':
    uvicorn.run(app, host='localhost', port=5000)
