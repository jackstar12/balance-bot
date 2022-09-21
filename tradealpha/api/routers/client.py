import functools
import itertools
import logging
import operator
import time
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Type, Iterable

import aiohttp
import jwt
import pytz
from fastapi import APIRouter, Depends, Request, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select, asc, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTasks

import tradealpha.api.utils.client as client_utils
from tradealpha.api.authenticator import Authenticator
from tradealpha.api.dependencies import get_authenticator, get_messenger, get_db, \
    FilterQueryParamsDep
from tradealpha.api.models.client import ClientConfirm, ClientEdit, \
    ClientOverview, Transfer, ClientCreateBody, ClientInfo, ClientCreateResponse, get_query_params
from tradealpha.api.models.trade import Trade, BasicTrade, DetailledTrade
from tradealpha.api.settings import settings
from tradealpha.api.users import CurrentUser
from tradealpha.api.utils.responses import BadRequest, OK, CustomJSONResponse, NotFound, ResponseModel
from tradealpha.common import utils
from tradealpha.common.calc import calc_daily
from tradealpha.common.dbasync import db_first, db_all, redis, async_maker
from tradealpha.common.dbmodels import TradeDB, BalanceDB
from tradealpha.common.dbmodels.client import Client, add_client_filters
from tradealpha.common.dbmodels.mixins.querymixin import QueryParams
from tradealpha.common.dbmodels.pnldata import PnlData
from tradealpha.common.dbmodels.user import User
from tradealpha.common.enums import IntervalType
from tradealpha.common.exchanges import EXCHANGES
from tradealpha.common.exchanges.exchangeworker import ExchangeWorker
from tradealpha.common.models import BaseModel, OrmBaseModel
from tradealpha.common.models.balance import Balance
from tradealpha.common.redis.client import ClientCacheKeys
from tradealpha.common.utils import validate_kwargs

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
                client = body.create()

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
                        payload = jsonable_encoder(body)
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
                         db: AsyncSession = Depends(get_db)):
    client_data = ClientCreateBody(
        **jwt.decode(body.token, settings.authjwt_secret_key, algorithms=['HS256'])
    )
    try:
        client = client_data.create(user)
        db.add(client)
        await db.commit()
        return ClientInfo.from_orm(client)
    except TypeError:
        return BadRequest(detail='Invalid token')


OverviewCache = client_utils.ClientCacheDependency(
    ClientCacheKeys.OVERVIEW,
    ClientOverview
)


@router.get('/client', response_model=ClientOverview)
async def get_client_overview(background_tasks: BackgroundTasks,
                              cache: client_utils.ClientCache[ClientOverview] = Depends(OverviewCache),
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

            daily = await calc_daily(
                client,
                since=query_params.since,
                to=query_params.to,
                db=db
            )

            overview: ClientOverview = ClientOverview.construct(
                initial_balance=(
                    Balance.from_orm(
                        await client.get_exact_balance_at_time(query_params.since, db=db)
                        if query_params.since else
                        await db_first(
                            client.history.statement.order_by(asc(BalanceDB.time)),
                            session=db
                        )
                    )
                ),
                current_balance=(
                    Balance.from_orm(
                        await client.get_exact_balance_at_time(query_params.to, db=db)
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
        for day, interval in itertools.chain.from_iterable((overview.daily.items() for overview in overviews)):
            if day in daily:
                daily[day] += interval
            else:
                daily[day] = interval

        def custom_sum(iterator: Iterable):
            return functools.reduce(operator.add, iterator)

        overview = ClientOverview.construct(
            daily=daily,
            initial_balance=custom_sum(overview.initial_balance for overview in overviews),
            current_balance=custom_sum(overview.current_balance for overview in overviews if overview.current_balance),
            transfers=functools.reduce(
                operator.or_,
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
async def delete_client(id: int,
                        user: User = Depends(CurrentUser),
                        db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        add_client_filters(delete(Client), user, {id}),
    )
    await db.commit()
    if result.rowcount == 1:
        return OK(detail='Success')
    else:
        return NotFound(detail='Invalid ID')


@router.patch('/client/{client_id}', response_model=ClientInfo)
async def update_client(client_id: int, body: ClientEdit,
                        user: User = Depends(CurrentUser),
                        db: AsyncSession = Depends(get_db)):
    client = await client_utils.get_user_client(
        user, client_id, db=db
    )

    if client:
        for k, v in body.dict(exclude_none=True).items():
            setattr(client, k, v)

        client.validate()
    else:
        return BadRequest('Invalid client id')

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

    @router.get(f'/client/{path}', response_model=ResponseModel[list[model]], **kwargs)
    async def get_trades(background_tasks: BackgroundTasks,
                         trade_id: list[int] = Query(None, alias='trade-id'),
                         cache: client_utils.ClientCache = Depends(TradeCache),
                         query_params: QueryParams = Depends(get_query_params),
                         filter_params: FilterQueryParams = Depends(FilterQueryParams),
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
        ts1 = time.perf_counter()
        hits, misses = await cache.read(db)
        print('missed: ', misses)
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
            trade for trades in hits for trade in trades.data
            if all(f.check(trade) for f in filter_params)
        ]
        ts4 = time.perf_counter()
        print('Cache Reading: ', ts2 - ts1)
        print('Query: ', ts4 - ts2)
        return OK(
            result=res
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
            .where(PnlData.trade_id.in_(trade_id))
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
    TradeDB.count,
    TradeDB.gross_win,
    TradeDB.gross_loss,
    TradeDB.total_commissions_stmt.label('total_commissions')
)


@router.get('/client/performance', response_model=ResponseModel[list[PnlStats]])
async def get_client_performance(interval: IntervalType = Query(default=None),
                                 trade_id: list[int] = Query(default=None),
                                 query_params: QueryParams = Depends(get_query_params),
                                 user: User = Depends(CurrentUser),
                                 db: AsyncSession = Depends(get_db)):
    ts1 = time.perf_counter()

    test = (await db.execute(text("""
SELECT count(*) AS count, date_trunc('day', trade.open_time) AS date 
FROM trade GROUP BY date_trunc('day', trade.open_time)
    """))).all()

    if interval:
        stmt = performance_base_select.add_columns(
            func.date_trunc('day', TradeDB.open_time).label('date')
        ).group_by(
            #func.date_trunc('day', TradeDB.open_time).label('date')
            TradeDB.open_time
        )
    else:
        stmt = performance_base_select

    stmt = add_client_filters(
        stmt.where(
            TradeDB.open_time > query_params.since if query_params.since else True,
            TradeDB.open_time < query_params.to if query_params.to else True,
            TradeDB.id.in_(trade_id) if trade_id else True
        ).join(
            TradeDB.client
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
            date=result.date if interval else None,
            count=result.count
        ))

    ts3 = time.perf_counter()
    print('Performance')
    print(ts2 - ts1)
    print(ts3 - ts2)
    return OK(
        result=jsonable_encoder(response)
    )


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
