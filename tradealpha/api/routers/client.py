import asyncio
import functools
import itertools
import logging
import operator
from datetime import datetime, date, timedelta
from http import HTTPStatus
from typing import Optional, Dict, List, Tuple
import aiohttp
import ccxt
import jwt
import pytz
from fastapi import APIRouter, Depends, Request, Response, WebSocket, Query, Body
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError, BaseModel
from sqlalchemy import or_, delete, select, update, asc, func, desc, Date, false
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from tradealpha.common.dbmodels.pnldata import PnlData
from tradealpha.api.utils.analytics import create_cilent_analytics
from tradealpha.api.authenticator import Authenticator
from tradealpha.api.models.analytics import ClientAnalytics, FilteredPerformance
from tradealpha.common.dbasync import db, db_first, async_session, db_all, db_select, redis, redis_bulk_keys, \
    redis_bulk_hashes, redis_bulk
from tradealpha.common.dbmodels.guildassociation import GuildAssociation
from tradealpha.common.dbmodels.guild import Guild
from tradealpha.api.models.client import RegisterBody, DeleteBody, ConfirmBody, UpdateBody, ClientQueryParams, \
    ClientOverview, Balance, Transfer
from tradealpha.api.models.websocket import WebsocketMessage, ClientConfig
from tradealpha.api.utils.responses import BadRequest, OK, CustomJSONResponse
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

from tradealpha.common.exchanges.exchangeworker import ExchangeWorker
from tradealpha.common.exchanges import EXCHANGES
from tradealpha.common.utils import validate_kwargs, create_interval
from tradealpha.common.dbmodels import TradeDB, BalanceDB
from tradealpha.api.models.trade import Trade, BasicTrade, DetailledTrade
from tradealpha.common.models.daily import Daily
from tradealpha.common.redis.client import ClientSpace, ClientCache

router = APIRouter(
    tags=["client"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


@router.post('/client')
async def register_client(request: Request, body: RegisterBody,
                          authenticator: Authenticator = Depends(get_authenticator),
                          db: AsyncSession = Depends(get_db)):
    await authenticator.verify_id(request)
    try:
        exchange_cls = EXCHANGES[body.exchange]
        if issubclass(exchange_cls, ExchangeWorker):
            # Check if required keyword args are given
            if validate_kwargs(body.extra or {}, exchange_cls.required_extra_args):
                client = Client(
                    name=body.name,
                    api_key=body.api_key,
                    api_secret=body.api_secret,
                    subaccount=body.subaccount,
                    extra_kwargs=body.extra,
                    exchange=body.exchange
                )
                async with aiohttp.ClientSession() as http_session:
                    worker = exchange_cls(client, http_session, db_session=db)
                    init_balance = await worker.get_balance(date=datetime.now(pytz.utc))
                    await worker.cleanup()
                if init_balance.error is None:
                    if init_balance.realized.is_zero():
                        return BadRequest(
                            f'You do not have any balance in your account. Please fund your account before registering.'
                        )
                    else:
                        payload = await client.serialize(full=True, data=True)
                        # TODO: CHANGE THIS
                        payload['api_secret'] = client.api_secret

                        return JSONResponse(jsonable_encoder({
                            'msg': 'Success',
                            'token': jwt.encode(payload, settings.authjwt_secret_key, algorithm='HS256'),
                            'balance': await init_balance.serialize()
                        }))
                else:
                    return BadRequest(f'An error occured while getting your balance: {init_balance.error}.')
            else:
                logging.error(
                    f'Not enough kwargs for exchange {exchange_cls.exchange} were given.'
                    f'\nGot: {body.extra}\nRequired: {exchange_cls.required_extra_args}'
                )
                args_readable = '\n'.join(exchange_cls.required_extra_args)
                return BadRequest(
                    detail=f'Need more keyword arguments for exchange {exchange_cls.exchange}.'
                           f'\nRequirements:\n {args_readable}',
                    code=40100
                )

        else:
            logging.error(f'Class {exchange_cls} is no subclass of ClientWorker!')
    except KeyError:
        return BadRequest(f'Exchange {body.exchange} unknown')


@router.get('/client')
async def get_client(request: Request, response: Response,
                     client_params: ClientQueryParams = Depends(),
                     user: User = Depends(CurrentUser),
                     db_session: AsyncSession = Depends(get_db)):
    non_cached = []
    overviews = []

    any_client = False
    if not client_params.id:
        client_params.id = [None]
        any_client = True

    # We want to first read data from cache
    pairs = {}
    for client_id in client_params.id:
        pairs[Client.redis_key(user.id, client_id)] = (
            ClientSpace.LAST_EXEC,
            ClientSpace.USER_ID
        )
        pairs[Client.cache_key(user.id, client_id)] = (
            utils.join_args(ClientCache.OVERVIEW_EXEC_TS),
        )
    data = await redis_bulk(pairs, redis_instance=redis)

    for client_id in client_params.id:

        last_exec, user_id = data[Client.redis_key(user.id, client_id)]
        cached_last_exec, = data[Client.cache_key(user.id, client_id)]
        if user_id or True:
            if user_id == user.id or True:
                if cached_last_exec and cached_last_exec > last_exec or True:
                    raw_overview = await Client.read_cache(
                        user.id,
                        ClientCache.OVERVIEW.value,
                        id=client_id
                    )
                    if raw_overview:
                        overviews.append(
                            ClientOverview(**customjson.loads(raw_overview))
                        )
                    else:
                        non_cached.append(client_id)
                else:
                    non_cached.append(client_id)
            else:
                pass  # Illegal access
        else:
            non_cached.append(client_id)

    if non_cached:
        # All clients that weren't found in cache have to be read from DB
        clients = await client_utils.get_user_clients(
            user,
            None if any_client else non_cached,
            (Client.trades, [
                TradeDB.executions,
                TradeDB.labels
            ]),
            Client.transfers,
            db=db_session
        )
        for client in clients:
            # We always want to fetch the last balance of the date (first balance of next date),
            # so we need to partition by the current date and order by
            # time in descending order so that we can pick out the first (last) one
            subq = select(
                func.row_number().over(
                    order_by=desc(BalanceDB.time),
                    partition_by=BalanceDB.time.cast(Date)
                ).label('row_number'),
                BalanceDB.id.label('id')
            ).filter(
                BalanceDB.client_id == client.id,
            ).subquery()
            stmt = select(
                BalanceDB,
                subq
            ).filter(
                subq.c.row_number == 1,
                BalanceDB.id == subq.c.id
            )
            daily = await db_all(stmt, session=db_session)

            overview = ClientOverview.construct(
                initial_balance=(
                    Balance.from_orm(
                        await client.get_balance_at_time(client_params.since)
                        if client_params.since else
                        await db_first(
                            client.history.statement.order_by(asc(BalanceDB.time)),
                            session=db_session
                        )
                    )
                ),
                current_balance=(
                    Balance.from_orm(
                        await client.get_balance_at_time(client_params.to)
                        if client_params.to else
                        await client.get_latest_balance(redis=redis)
                        # await client.latest()
                    )
                ),
                trades_by_id={
                    str(trade.id): Trade.from_orm(trade)
                    for trade in client.trades
                },
                daily={
                    balance.time.date(): Balance.from_orm(balance)
                    for balance in daily
                },
                transfers={
                    str(transfer.id): Transfer.from_orm(transfer)
                    for transfer in client.transfers
                }
            )
            asyncio.create_task(client.set_cache(client.id,
                                                 user.id,
                                                 keys={
                                                     ClientCache.OVERVIEW.value:
                                                         customjson.dumps(jsonable_encoder(overview)),
                                                     ClientCache.OVERVIEW_EXEC_TS.value:
                                                         str(data.get(Client.cache_key(user.id, client.id), 0))
                                                 }))
            overviews.append(overview)

    if overviews:
        daily = {}
        for daily_balance in itertools.chain.from_iterable((overview.daily.values() for overview in overviews)):
            day = daily_balance.time.date()
            if day in daily:
                daily[day] += daily_balance
            else:
                daily[day] = daily_balance

        overview = ClientOverview.construct(
            daily=daily,
            initial_balance=functools.reduce(
                operator.add, (overview.initial_balance for overview in overviews)
            ),
            current_balance=functools.reduce(
                operator.add, (overview.current_balance for overview in overviews if overview.current_balance)
            ),
            trades_by_id=functools.reduce(
                lambda a, b: a | b,
                (overview.trades_by_id for overview in overviews)
            ),
            transfers=functools.reduce(
                lambda a, b: a | b,
                (overview.transfers for overview in overviews)
            )
        )
        encoded = jsonable_encoder(overview)
        return CustomJSONResponse(content=encoded)
    else:
        return BadRequest('Invalid client id', 40000)


@router.delete('/client')
async def delete_client(body: DeleteBody, user: User = Depends(CurrentUser)):
    await db(
        add_client_filters(delete(Client), user, [body.id])
    )
    await async_session.commit()
    return OK(detail='Success')


@router.patch('/client')
async def update_client(body: UpdateBody, user: User = Depends(CurrentUserDep(User.discord_user))):
    client: Client = await db_first(
        add_client_filters(select(Client), user, [body.id])
    )

    if body.name is not None:
        client.name = body.name

    if body.archived is not None:
        client.archived = body.archived

    # Check explicitly for False and True because we don't want to do anything on None
    if body.discord is False:
        client.discord_user_id = None
        client.user_id = user.id
        await db(
            update(GuildAssociation).where(
                GuildAssociation.client_id == client.id
            ).values(client_id=None)
        )

    elif body.discord is True:
        if user.discord_user_id:
            client.discord_user_id = user.discord_user_id
            client.user_id = None
            if body.servers is not None:

                if body.servers:
                    await db(
                        update(GuildAssociation).where(
                            GuildAssociation.discord_user_id == user.discord_user_id,
                            GuildAssociation.guild_id.in_(body.servers)
                        ).values(client_id=client.id)
                    )

                await db(
                    update(GuildAssociation).where(
                        GuildAssociation.discord_user_id == user.discord_user_id,
                        GuildAssociation.client_id == client.id,
                        GuildAssociation.guild_id.not_in(body.servers)
                    ).values(client_id=None)
                )

                # guilds: List[Guild] = await db_all(
                #    select(Guild).filter(
                #        or_(*[Guild.id == guild_id for guild_id in body.servers]),
                #    ),
                #    Guild.users
                # )
                # for guild in guilds:
                #    if user.discord_user in guild.users:
                #        guild.global_clients.append(
                #            GuildAssociation(
                #                discord_user_id=user.discord_user_id,
                #                client_id=client.id
                #            )
                #        )
                #    else:
                #        return BadRequest(f'You are not eligible to register in guild {guild.name}')
                await async_session.commit()
            if body.events is not None:
                now = datetime.now(tz=pytz.UTC)
                if body.events:
                    events = await db_all(
                        select(db_event.Event).filter(
                            db_event.Event.id.in_(body.events)
                        )
                    )
                else:
                    events = []
                valid_events = []
                for event in events:
                    if event.is_free_for_registration(now):
                        if event.guild in user.discord_user.guilds:
                            valid_events.append(event)
                        else:
                            return BadRequest(f'You are not eligible to join {event.name} (Not in server)')
                    else:
                        return BadRequest(f'Event {event.name} is not free for registration')
                client.events = valid_events

            if body.servers is None and body.events is None:
                return BadRequest('Either servers or events have to be provided')
        else:
            return BadRequest('No discord account found')

    await async_session.commit()
    return OK('Changes applied')


@router.post('/client/confirm')
async def confirm_client(body: ConfirmBody,
                         user: User = Depends(CurrentUser),
                         messenger: Messenger = Depends(get_messenger),
                         db_session: AsyncSession = Depends(get_db)):
    client_json = jwt.decode(body.token, settings.authjwt_secret_key, algorithms=['HS256'])
    print(client_json)
    try:
        client = Client(**client_json)
        client.user = user
        db_session.add(client)
        await db_session.commit()
        add_client(client, messenger)
        return OK('Success')
    except TypeError:
        return BadRequest(detail='Invalid token')


def create_ws_message(type: str, channel: str = None, data: Dict = None, error: str = None, *args):
    return {
        "type": type,
        "channel": channel,
        "data": data,
        "error": error
    }


@router.websocket('/client/ws')
async def client_websocket(websocket: WebSocket, csrf_token: str = Query(...),
                           authenticator: Authenticator = Depends(get_authenticator)):
    await websocket.accept()

    authenticator.verify_id()
    subscribed_client: Optional[Client] = None
    config: Optional[ClientConfig] = None
    messenger = Messenger()

    async def send_client_snapshot(client: Client, type: str, channel: str):
        msg = jsonable_encoder(create_ws_message(
            type=type,
            channel=channel,
            data=await create_client_data_serialized(
                client,
                config
            )
        ))
        await websocket.send_json(msg)

    def unsub_client(client: Client):
        if client:
            messenger.unsub_channel(NameSpace.BALANCE, sub=Category.NEW, channel_id=client.id)
            messenger.unsub_channel(NameSpace.TRADE, sub=Category.NEW, channel_id=client.id)
            messenger.unsub_channel(NameSpace.TRADE, sub=Category.UPDATE, channel_id=client.id)
            messenger.unsub_channel(NameSpace.TRADE, sub=Category.UPNL, channel_id=client.id)

    async def update_client(old: Client, new: Client):

        unsub_client(old)
        await send_client_snapshot(new, type='initial', channel='client')

        async def send_json_message(json: Dict):
            await websocket.send_json(
                jsonable_encoder(json)
            )

        async def send_upnl_update(data: Dict):
            await send_json_message(
                create_ws_message(
                    type='trade',
                    channel='upnl',
                    data=data
                )
            )

        async def send_trade_update(trade: Dict):
            await send_json_message(
                create_ws_message(
                    type='client',
                    channel='update',
                    data=client_utils.update_client_data_trades(
                        await client_utils.get_cached_data(config),
                        [trade],
                        config
                    )
                )
            )

        async def send_balance_update(balance: Dict):
            await send_json_message(
                create_ws_message(
                    type='client',
                    channel='update',
                    data=await client_utils.update_client_data_balance(
                        await client_utils.get_cached_data(config),
                        subscribed_client,
                        config
                    )
                )
            )

        await messenger.sub_channel(
            NameSpace.BALANCE, sub=Category.NEW, channel_id=new.id,
            callback=send_balance_update
        )

        await messenger.sub_channel(
            NameSpace.TRADE, sub=Category.NEW, channel_id=new.id,
            callback=send_trade_update
        )

        await messenger.sub_channel(
            NameSpace.TRADE, sub=Category.UPDATE, channel_id=new.id,
            callback=send_trade_update
        )

        await messenger.sub_channel(
            NameSpace.TRADE, sub=Category.UPNL, channel_id=new.id,
            callback=send_upnl_update
        )

    while True:
        try:
            raw_msg = await websocket.receive_json()
            msg = WebsocketMessage(**raw_msg)
            print(msg)
            if msg.type == 'ping':
                await websocket.send_json(create_ws_message(type='pong'))
            elif msg.type == 'subscribe':
                id = msg.data.get('id')
                new_client = await get_user_client(user, id)

                if not new_client:
                    await websocket.send_json(create_ws_message(
                        type='error',
                        error='Invalid Client ID'
                    ))
                else:
                    await update_client(old=subscribed_client, new=new_client)
                    subscribed_client = new_client

            elif msg.type == 'update':
                if msg.channel == 'config':
                    config = ClientConfig(**msg.data)
                    logging.info(config)
                    new_client = await get_user_client(user, config.id)
                    if not new_client:
                        await websocket.send_json(create_ws_message(
                            type='error',
                            error='Invalid Client ID'
                        ))
                    else:
                        config.id = new_client.id
                        config.currency = config.currency or '$'
                        await update_client(old=subscribed_client, new=new_client)
                        subscribed_client = new_client
        except ValidationError as e:
            await websocket.send_json(create_ws_message(
                type='error',
                error=str(e)
            ))
        except WebSocketDisconnect:
            unsub_client(subscribed_client)
            break


@router.get('/client/trade-overview', response_model=List[BasicTrade])
async def get_trade_overview(client_params: ClientQueryParams = Depends(),
                             trade_id: list[int] = Query(None, alias='trade-id'),
                             user: User = Depends(CurrentUser),
                             db_session: AsyncSession = Depends(get_db)):
    trades = await client_utils.query_trades(
        user=user,
        client_params=client_params,
        trade_id=trade_id,
        db_session=db_session
    )

    return CustomJSONResponse(
        content=jsonable_encoder([
            jsonable_encoder(BasicTrade.from_orm(trade))
            for trade in trades
        ])
    )


@router.get('/client/trade-detailled', response_model=List[DetailledTrade])
async def get_detailled_trades(client_params: ClientQueryParams = Depends(),
                               trade_id: list[int] = Query(None, alias='trade-id'),
                               user: User = Depends(CurrentUser),
                               db_session: AsyncSession = Depends(get_db)):
    trades = await client_utils.query_trades(
        TradeDB.executions,
        TradeDB.initial,
        TradeDB.max_pnl,
        TradeDB.min_pnl,
        TradeDB.labels,
        TradeDB.init_balance,
        user=user,
        client_params=client_params,
        trade_id=trade_id,
        db_session=db_session
    )

    return CustomJSONResponse(
        content=jsonable_encoder([
            jsonable_encoder(DetailledTrade.from_orm(trade))
            for trade in trades
        ])
    )


@router.get('/client/trade-detailled/pnl-data')
async def get_detailled_trades(trade_id: list[int] = Query(..., alias='trade-id'),
                               user: User = Depends(CurrentUser),
                               db_session: AsyncSession = Depends(get_db)):
    data: List[PnlData] = await db_all(
        add_client_filters(
            select(PnlData)
            .filter(PnlData.trade_id.in_(trade_id))
            .join(PnlData.trade)
            .join(TradeDB.client)
            .order_by(asc(PnlData.time)),
            user=user
        ),
        session=db_session
    )

    result = {}
    for pnl_data in data:
        result.setdefault(pnl_data.trade_id, []).append(pnl_data.compact())

    return CustomJSONResponse(content=jsonable_encoder(result))


@router.get('/client/trade', response_model=List[Trade])
async def get_trades(client_params: ClientQueryParams = Depends(),
                     trade_id: list[int] = Query(None, alias='trade-id'),
                     user: User = Depends(CurrentUser),
                     db_session: AsyncSession = Depends(get_db)):
    trades = await client_utils.query_trades(
        TradeDB.executions,
        TradeDB.labels,
        user=user,
        client_params=client_params,
        trade_id=trade_id,
        db_session=db_session
    )
    return CustomJSONResponse(
        content=[
            jsonable_encoder(Trade.from_orm(trade))
            for trade in trades
        ]
    )
