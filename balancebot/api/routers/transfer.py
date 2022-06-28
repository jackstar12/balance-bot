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

from balancebot.api.models.transfer import Transfer
from balancebot.api.utils.analytics import create_cilent_analytics
from balancebot.api.authenticator import Authenticator
from balancebot.api.models.analytics import ClientAnalytics, FilteredPerformance, TradeAnalytics
from balancebot.common.dbasync import db, db_first, async_session, db_all, db_select, redis, redis_bulk_keys, \
    redis_bulk_hashes, redis_bulk
from balancebot.common.dbmodels.guildassociation import GuildAssociation
from balancebot.common.dbmodels.guild import Guild
from balancebot.api.models.client import RegisterBody, DeleteBody, ConfirmBody, UpdateBody, ClientQueryParams, \
    ClientOverview, Balance
from balancebot.common.dbmodels.transfer import TransferDB
from balancebot.api.models.websocket import WebsocketMessage, ClientConfig
from balancebot.api.utils.responses import BadRequest, OK, CustomJSONResponse, NotFound
from balancebot.common import utils, customjson
from balancebot.api.dependencies import CurrentUser, CurrentUserDep, get_authenticator, get_messenger, get_db
from balancebot.common.dbsync import session
from balancebot.common.dbmodels.client import Client, add_client_filters
from balancebot.common.dbmodels.user import User
from balancebot.api.settings import settings
from balancebot.api.utils.client import create_client_data_serialized, get_user_client
import balancebot.api.utils.client as client_utils
from balancebot.common.dbutils import add_client
from balancebot.common.messenger import Messenger, NameSpace, Category, Word
import balancebot.common.dbmodels.event as db_event

from balancebot.common.exchanges import EXCHANGES
from balancebot.common.utils import validate_kwargs, create_interval
from balancebot.common.dbmodels import TradeDB, BalanceDB
from balancebot.api.models.trade import Trade
from balancebot.common.models.daily import Daily
from balancebot.common.redis.client import ClientSpace, ClientCache

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
