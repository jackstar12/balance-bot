import asyncio
import functools
import itertools
import logging
import operator
from datetime import datetime, date, timedelta
from http import HTTPStatus
from typing import Optional, Dict, List, Tuple
import aiohttp
import jwt
import pytz
from fastapi import APIRouter, Depends, Request, Response, WebSocket, Query, Body
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import or_, delete, select, update, asc, func, desc, Date, false
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from tradealpha.api.models.transfer import Transfer
from tradealpha.api.utils.analytics import create_cilent_analytics
from tradealpha.api.authenticator import Authenticator
from tradealpha.api.models.analytics import ClientAnalytics, FilteredPerformance, TradeAnalytics
from tradealpha.common.dbasync import db, db_first, async_session, db_all, db_select, redis, redis_bulk_keys, \
    redis_bulk_hashes, redis_bulk
from tradealpha.common.dbmodels.guildassociation import GuildAssociation
from tradealpha.common.dbmodels.guild import Guild
from tradealpha.api.models.client import RegisterBody, DeleteBody, ConfirmBody, UpdateBody, ClientQueryParams, \
    ClientOverview, Balance
from tradealpha.common.dbmodels.transfer import TransferDB
from tradealpha.api.models.websocket import WebsocketMessage, ClientConfig
from tradealpha.api.utils.responses import BadRequest, OK, CustomJSONResponse, NotFound
from tradealpha.common import utils, customjson
from tradealpha.api.dependencies import CurrentUser, CurrentUserDep, get_authenticator, get_messenger, get_db
from tradealpha.common.dbsync import session
from tradealpha.common.dbmodels.client import Client, add_client_filters
from tradealpha.common.dbmodels.user import User
from tradealpha.api.settings import settings
from tradealpha.api.utils.client import create_client_data_serialized, get_user_client
import tradealpha.api.utils.client as client_utils
from tradealpha.common.dbutils import add_client
from tradealpha.common.messenger import Messenger, NameSpace, Category, Word
import tradealpha.common.dbmodels.event as db_event

from tradealpha.common.exchanges import EXCHANGES
from tradealpha.common.utils import validate_kwargs, create_interval
from tradealpha.common.dbmodels import TradeDB, BalanceDB
from tradealpha.api.models.trade import Trade
from tradealpha.common.models.daily import Daily
from tradealpha.common.redis.client import ClientSpace, ClientCache

router = APIRouter(
    tags=["transfer"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


@router.get('/{transfer_id}')
async def update_transfer(transfer_id: int,
                          user: User = Depends(CurrentUser)):
    transfer = await db_first(
        add_client_filters(
            select(TransferDB).filter_by(
                id=transfer_id
            ).join(
                TransferDB.client
            ),
            user=user
        )
    )

    if transfer:
        return Transfer.from_orm(transfer)
    else:
        return NotFound('Invalid transfer_id')


@router.patch('/{transfer_id}')
async def update_transfer(transfer_id: int,
                          note: str = Body(...),
                          user: User = Depends(CurrentUser),
                          db_session: AsyncSession = Depends(get_db)):
    await db(
        update(TransferDB).
        where(TransferDB.id == transfer_id).
        where(TransferDB.client_id == Client.id).
        where(Client.user_id == user.id).
        values(note=note),
        session=db_session
    )

    await db_session.commit()

    return OK('Updated')
