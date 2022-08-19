import asyncio
import functools
import itertools
import json
import logging
import operator
import time
from datetime import datetime, date, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import Optional, Dict, List, Tuple, Type
import aiohttp
import ccxt
import jwt
import pytz
from fastapi import APIRouter, Depends, Request, Response, WebSocket, Query, Body
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import or_, delete, select, update, asc, func, desc, Date, false, case
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTasks
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from tradealpha.common.models.balance import Balance
from tradealpha.common.dbmodels.mixins.querymixin import QueryParams
from tradealpha.common.dbmodels.execution import Execution
from tradealpha.common.models import BaseModel, OrmBaseModel
from tradealpha.common.dbmodels.pnldata import PnlData
from tradealpha.api.utils.analytics import create_cilent_analytics
from tradealpha.api.authenticator import Authenticator
from tradealpha.api.models.analytics import ClientAnalytics, FilteredPerformance
from tradealpha.common.dbasync import db_exec, db_first, db_all, db_select, redis, redis_bulk_keys, \
    redis_bulk_hashes, redis_bulk, async_maker
from tradealpha.common.dbmodels.guildassociation import GuildAssociation
from tradealpha.common.dbmodels.guild import Guild
from tradealpha.api.models.client import ClientConfirm, ClientEdit, \
    ClientOverview, Transfer, ClientCreateBody, ClientInfo, ClientCreateResponse, get_query_params
from tradealpha.api.models.websocket import WebsocketMessage, ClientConfig
from tradealpha.api.utils.responses import BadRequest, OK, CustomJSONResponse, NotFound
from tradealpha.common import utils, customjson
from tradealpha.api.dependencies import CurrentUser, CurrentUserDep, get_authenticator, get_messenger, get_db, \
    FilterQueryParamsDep
from tradealpha.common.dbsync import session
from tradealpha.common.dbmodels.client import Client, add_client_filters
from tradealpha.common.dbmodels.user import User
from tradealpha.api.settings import settings
from tradealpha.api.utils.client import create_client_data_serialized, get_user_client
import tradealpha.api.utils.client as client_utils
from tradealpha.common.dbutils import register_client, delete_client
from tradealpha.common.messenger import Messenger, NameSpace, Category, Word
import tradealpha.common.dbmodels.event as db_event

from tradealpha.common.exchanges.exchangeworker import ExchangeWorker
from tradealpha.common.exchanges import EXCHANGES
from tradealpha.common.utils import validate_kwargs
from tradealpha.common.dbmodels import TradeDB, BalanceDB
from tradealpha.api.models.trade import Trade, BasicTrade, DetailledTrade
from tradealpha.common.redis.client import ClientSpace, ClientCacheKeys

router = APIRouter(
    tags=["client"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


@router.post('/client', response_model=ClientCreateResponse)
async def new_client(request: Request, body: ClientCreateBody,
                     authenticator: Authenticator = Depends(get_authenticator)):
    await authenticator.verify_id(request)
    try:
        exchange_cls = EXCHANGES[body.exchange]
        if issubclass(exchange_cls, ExchangeWorker):
            # Check if required keyword args are given
            if validate_kwargs(body.extra_kwargs or {}, exchange_cls.required_extra_args):
                client = body.create_client()
                async with aiohttp.ClientSession() as http_session:
                    worker = exchange_cls(client, http_session, db_maker=async_maker)
                    init_balance = await worker.get_balance(date=datetime.now(pytz.utc))
                    await worker.cleanup()

                if init_balance.error is None:
                    if init_balance.realized.is_zero():
                        return BadRequest(
                            f'You do not have any balance in your account. Please fund your account before registering.'
                        )
                    else:
                        payload = body.dict()
                        # TODO: CHANGE THIS
                        payload['api_secret'] = client.api_secret

                        return ClientCreateResponse(
                            token=jwt.encode(payload, settings.authjwt_secret_key, algorithm='HS256'),
                            balance=Balance.from_orm(init_balance)
                        )
                else:
                    return BadRequest(f'An error occured while getting your balance: {init_balance.error}.')
            else:
                logging.error(
                    f'Not enough kwargs for exchange {exchange_cls.exchange} were given.'
                    f'\nGot: {body.extra_kwargs}\nRequired: {exchange_cls.required_extra_args}'
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


@router.post('/client/confirm', response_model=ClientInfo)
async def confirm_client(body: ClientConfirm,
                         user: User = Depends(CurrentUser),
                         messenger: Messenger = Depends(get_messenger),
                         db: AsyncSession = Depends(get_db)):
    client_data = ClientCreateBody(
        **jwt.decode(body.token, settings.authjwt_secret_key, algorithms=['HS256'])
    )
    try:
        client = client_data.create_client(user)
        await register_client(client, messenger, db)
        return ClientInfo.from_orm(client)
    except TypeError:
        return BadRequest(detail='Invalid token')


OverviewCache = client_utils.ClientCacheDependency(
    ClientCacheKeys.OVERVIEW,
    ClientOverview
)


@router.get('/client', response_model=ClientOverview)
async def get_client_overview(background_tasks: BackgroundTasks,
                              cache: client_utils.ClientCache = Depends(OverviewCache),
                              query_params: QueryParams = Depends(get_query_params),
                              user: User = Depends(CurrentUser),
                              db: AsyncSession = Depends(get_db)):
    any_client = False
    if not query_params.client_ids:
        # query_params.client_ids = [None]
        any_client = True

    overviews, non_cached = await cache.read(db)

    if non_cached:
        # All clients that weren't found in cache have to be read from DB
        clients = await client_utils.get_user_clients(
            user,
            None if any_client else non_cached,
            Client.transfers,
            db=db
        )
        for client in clients:
            # We always want to fetch the last balance of the date (first balance of next date),
            # so we need to partition by the current date and order by
            # time in descending order so that we can pick out the first (last) one

            daily = await utils.calc_daily(
                client,
                db=db
            )

            overview: ClientOverview = ClientOverview.construct(
                initial_balance=(
                    Balance.from_orm(
                        await client.get_balance_at_time(query_params.since, db=db)
                        if query_params.since else
                        await db_first(
                            client.history.statement.order_by(asc(BalanceDB.time)),
                            session=db
                        )
                    )
                ),
                current_balance=(
                    Balance.from_orm(
                        await client.get_balance_at_time(query_params.to, db=db)
                        if query_params.to else
                        await client.get_latest_balance(redis=redis, db=db)
                        # await client.latest()
                    )
                ),
                daily={
                    utils.date_string(day.day): day
                    for day in daily
                },
                transfers={
                    str(transfer.id): Transfer.from_orm(transfer)
                    for transfer in client.transfers
                }
            )
            background_tasks.add_task(
                cache.write,
                client.id,
                overview,

            )
            overviews.append(overview)

    ts1 = time.perf_counter()
    if overviews:
        daily = {}
        overview: ClientOverview
        for interval in itertools.chain.from_iterable((overview.daily.values() for overview in overviews)):
            day = interval.day
            if day in daily:
                daily[day] += interval
            else:
                daily[day] = interval

        overview = ClientOverview.construct(
            daily=daily,
            initial_balance=functools.reduce(
                operator.add, (overview.initial_balance for overview in overviews)
            ),
            current_balance=functools.reduce(
                operator.add, (overview.current_balance for overview in overviews if overview.current_balance)
            ),
            transfers=functools.reduce(
                lambda a, b: a | b,
                (overview.transfers for overview in overviews)
            )
        )
        encoded = jsonable_encoder(overview)
        ts2 = time.perf_counter()
        print('encode', ts2 - ts1)
        return CustomJSONResponse(content=encoded)
    else:
        return BadRequest('Invalid client id', 40000)


@router.delete('/client/{id}')
async def delete_client_endpoint(id: int,
                                 user: User = Depends(CurrentUser),
                                 messenger: Messenger = Depends(get_messenger),
                                 db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        add_client_filters(delete(Client), user, [id]),
    )
    await db.commit()
    if result.rowcount == 1:
        messenger.pub_channel(NameSpace.CLIENT, Category.DELETE, obj={'id': id})
        return OK(detail='Success')
    else:
        return NotFound(detail='Invalid ID')


@router.patch('/client/{id}', response_model=ClientInfo)
async def update_client(id: int, body: ClientEdit,
                        user: User = Depends(CurrentUserDep(User.discord_user)),
                        db: AsyncSession = Depends(get_db)):
    client: Client = await db_first(
        add_client_filters(select(Client), user, [id]),
        session=db
    )

    if body.name is not None:
        client.name = body.name

    if body.archived is not None:
        client.archived = body.archived

    # Check explicitly for False and True because we don't want to do anything on None
    if body.discord is False:
        client.discord_user_id = None
        client.user_id = user.id
        await db_exec(
            update(GuildAssociation).where(
                GuildAssociation.client_id == client.id
            ).values(client_id=None),
            session=db
        )

    elif body.discord is True:
        if user.discord_user_id:
            client.discord_user_id = user.discord_user_id
            client.user_id = None
            if body.servers is not None:

                if body.servers:
                    await db_exec(
                        update(GuildAssociation).where(
                            GuildAssociation.discord_user_id == user.discord_user_id,
                            GuildAssociation.guild_id.in_(body.servers)
                        ).values(client_id=client.id),
                        session=db
                    )

                await db_exec(
                    update(GuildAssociation).where(
                        GuildAssociation.discord_user_id == user.discord_user_id,
                        GuildAssociation.client_id == client.id,
                        GuildAssociation.guild_id.not_in(body.servers)
                    ).values(client_id=None),
                    session=db
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
                await db.commit()
            if body.events is not None:
                now = datetime.now(tz=pytz.UTC)
                if body.events:
                    events = await db_all(
                        select(db_event.Event).filter(
                            db_event.Event.id.in_(body.events)
                        ),
                        session=db
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

    await db.commit()
    return ClientInfo.from_orm(client)


def create_trade_endpoint(path: str,
                          model: Type[OrmBaseModel],
                          *eager,
                          **kwargs):
    class Trades(BaseModel):
        data: list[model]

    TradeCache = client_utils.ClientCacheDependency(
        utils.join_args(ClientCacheKeys.TRADE, path),
        Trades
    )

    FilterQueryParams = FilterQueryParamsDep(model)

    @router.get(f'/client/{path}', response_model=model, **kwargs)
    async def get_trades(background_tasks: BackgroundTasks,
                         trade_id: list[int] = Query(None, alias='trade-id'),
                         cache: client_utils.ClientCache = Depends(TradeCache),
                         query_params: QueryParams = Depends(get_query_params),
                         filter_params: FilterQueryParams = Depends(),
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
        ts1 = time.perf_counter()
        hits, misses = await cache.read(db)
        ts2 = time.perf_counter()
        if misses:
            query_params.client_ids = misses
            trades_db = await client_utils.query_trades(
                *eager,
                user=user,
                query_params=query_params,
                trade_id=trade_id,
                db=db
            )
            trades_by_client = {}
            for trade_db in trades_db:
                if trade_db.client_id not in trades_by_client:
                    trades_by_client[trade_db.client_id] = Trades(data=[])
                trades_by_client[trade_db.client_id].data.append(
                    model.from_orm(trade_db)
                )
            for client_id, trades in trades_by_client.items():
                hits.append(trades)
                background_tasks.add_task(
                    cache.write,
                    client_id,
                    trades
                )

        res = [
            jsonable_encoder(trade) for trades in hits for trade in trades.data
            if all(f.check(trade) for f in filter_params)
        ]
        ts4 = time.perf_counter()
        print(ts2 - ts1)
        print(ts4 - ts2)
        return CustomJSONResponse(
            content={
                'data': res
            }
        )


create_trade_endpoint(
    'trade-overview',
    BasicTrade,
)
create_trade_endpoint(
    'trade',
    Trade,
    TradeDB.executions,
    TradeDB.labels,
)
create_trade_endpoint(
    'trade-detailled',
    DetailledTrade,
    TradeDB.executions,
    TradeDB.initial,
    TradeDB.max_pnl,
    TradeDB.min_pnl,
    TradeDB.pnl_data,
    TradeDB.labels,
    TradeDB.init_balance,
)


@router.get('/client/trade-detailled/pnl-data')
async def get_pnl_data(trade_id: list[int] = Query(..., alias='trade-id'),
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    data: List[PnlData] = await db_all(
        add_client_filters(
            select(PnlData)
            .filter(PnlData.trade_id.in_(trade_id))
            .join(PnlData.trade)
            .join(TradeDB.client)
            .order_by(asc(PnlData.time)),
            user=user
        ),
        session=db
    )

    result = {}
    for pnl_data in data:
        result.setdefault(pnl_data.trade_id, []).append(pnl_data.compact())

    return CustomJSONResponse(content=jsonable_encoder(result))


class PnlStat(OrmBaseModel):
    win: Decimal
    loss: Decimal
    total: Decimal


class PnlStats(OrmBaseModel):
    date: Optional[date]
    gross: PnlStat
    net: Decimal
    commissions: Decimal
    count: int


# Cache query
performance_base_select = select(
    func.count().label('count'),
    func.sum(
        case(
            {TradeDB.realized_pnl > 0: TradeDB.realized_pnl},
            else_=0
        )
    ).label('gross_win'),
    func.sum(
        case(
            {TradeDB.realized_pnl < 0: TradeDB.realized_pnl},
            else_=0
        )
    ).label('gross_loss'),
    func.sum(TradeDB.total_commissions).label('total_commissions'),
)


@router.get('/client/performance', response_model=list[PnlStats])
async def get_client_performance(daily: bool = Query(default=False),
                                 trade_id: list[int] = Query(default=None),
                                 query_params: QueryParams = Depends(get_query_params),
                                 user: User = Depends(CurrentUser),
                                 db: AsyncSession = Depends(get_db)):
    ts1 = time.perf_counter()

    # subq = select(
    #     func.row_number().over(
    #         order_by=desc(BalanceDB.time),
    #         partition_by=BalanceDB.time.cast(Date)
    #     ).label('row_number'),
    #     BalanceDB.id.label('id')
    # ).filter(
    #     BalanceDB.client_id == client.id,
    # ).subquery()

    if daily:
        stmt = performance_base_select.add_columns(
            TradeDB.open_time.cast(Date).label('date'),
        ).group_by(
            TradeDB.open_time.cast(Date)
        )
    else:
        stmt = performance_base_select

    stmt = add_client_filters(
        stmt.filter(
            TradeDB.open_time > query_params.since if query_params.since else True,
            TradeDB.open_time < query_params.to if query_params.to else True,
            TradeDB.id.in_(trade_id) if trade_id else True
        ),
        user=user,
        client_ids=query_params.client_ids
    )
    results = (await db.execute(stmt)).all()
    ts2 = time.perf_counter()
    response = []

    for result in results:
        gross_win = result.gross_win or 0
        gross_loss = result.gross_loss or 0
        commissions = result.total_commissions or 0
        response.append(PnlStats.construct(
            gross=PnlStat.construct(
                win=gross_win,
                loss=abs(gross_loss),
                total=gross_win + gross_loss
            ),
            commissions=commissions,
            net=gross_win + gross_loss - commissions,
            date=result.date if daily else None,
            count=result.count
        ))

    ts3 = time.perf_counter()
    print('Performance')
    print(ts2 - ts1)
    print(ts3 - ts2)
    return CustomJSONResponse(jsonable_encoder(response))


@router.get('/client/balance')
async def get_client_balance(balance_id: list[int] = Query(None, alias='balance-id'),
                             query_params: QueryParams = Depends(get_query_params),
                             user: User = Depends(CurrentUser),
                             db: AsyncSession = Depends(get_db)):
    balance = await BalanceDB.query(
        time_col=BalanceDB.time,
        user=user,
        ids=balance_id,
        params=query_params,
        db=db
    )
    return Balance.from_orm(balance)
