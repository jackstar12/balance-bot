import uvicorn
import asyncio
import logging
import os
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Optional

from fastapi_jwt_auth.exceptions import AuthJWTException
from starlette.responses import JSONResponse

from balancebot.bot.config import EXCHANGES
from pydantic import BaseModel
from fastapi import Depends
from fastapi_jwt_auth import AuthJWT
import flask_jwt_extended as flask_jwt
import jwt
from flask import request, jsonify
from sqlalchemy import or_
from fastapi import FastAPI, Request

from balancebot import utils
from balancebot.api.database import migrate, session

from balancebot.api.dbmodels.client import Client
from balancebot.api.dbmodels.user import User
from balancebot.api.settings import settings
from balancebot.exchangeworker import ExchangeWorker
from balancebot.api.database import Base, engine

import routers.discordauth as discord
import routers.authentication as auth
import routers.client as client
import routers.label as label

app = FastAPI(
    root_path='/api/v1'
)

Base.metadata.create_all(bind=engine)

app.include_router(discord.router, prefix='/api/v1')
app.include_router(auth.router, prefix='/api/v1')
app.include_router(client.router, prefix='/api/v1')
app.include_router(label.router, prefix='/api/v1')


@AuthJWT.load_config
def get_config():
    return settings


def current_user(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    user = session.query(User).filter_by(id=Authorize.get_jwt_subject()).first()
    return user


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
    return {'msg': 'Success'}, HTTPStatus.OK


@app.get('/api/v1/info')
def info(user: User = Depends(current_user)):
    return user.serialize(full=False, data=False), 200


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
    asyncio.create_task(bot.run())


if __name__ == '__main__':
    uvicorn.run(app, host='localhost', port=5000)
