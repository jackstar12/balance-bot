import functools
import itertools
import logging
import operator
import time
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Iterable

import aiohttp
import jwt
import pytz
from fastapi import APIRouter, Depends, Request, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select, asc, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTasks

import tradealpha.api.utils.client as client_utils
from api.models.trade import Trade, BasicTrade
from common.models.interval import Interval
from tradealpha.api.authenticator import Authenticator
from tradealpha.api.dependencies import get_authenticator, get_messenger, get_db
from tradealpha.api.models.client import ClientConfirm, ClientEdit, \
    ClientOverview, Transfer, ClientCreateBody, ClientInfo, ClientCreateResponse, get_query_params, ClientDetailed, \
    ClientOverviewCache
from tradealpha.api.settings import settings
from tradealpha.api.users import CurrentUser
from tradealpha.api.utils.responses import BadRequest, OK, CustomJSONResponse, NotFound, ResponseModel
from tradealpha.common import utils
from tradealpha.common.calc import calc_daily, create_daily
from tradealpha.common.dbasync import db_first, redis, async_maker, time_range, db_all
from tradealpha.common.dbmodels import TradeDB, BalanceDB
from tradealpha.common.dbmodels.client import Client, add_client_filters
from tradealpha.common.dbmodels.mixins.querymixin import QueryParams
from tradealpha.common.dbmodels.user import User
from tradealpha.common.enums import IntervalType
from tradealpha.common.exchanges import EXCHANGES
from tradealpha.common.exchanges.exchangeworker import ExchangeWorker
from tradealpha.common.models import OrmBaseModel, BaseModel, OutputID
from tradealpha.common.models.balance import Balance
from tradealpha.common.redis.client import ClientCacheKeys
from tradealpha.common.utils import validate_kwargs, groupby, date_string, sum_iter

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
                client = body.get()

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
        client = client_data.get(user)
        db.add(client)
        await db.commit()
        return ClientInfo.from_orm(client)
    except TypeError:
        return BadRequest(detail='Invalid token')


OverviewCache = client_utils.ClientCacheDependency(
    ClientCacheKeys.OVERVIEW,
    ClientOverviewCache
)


@router.get('/client/overview', response_model=ClientOverview)
async def get_client_overview(background_tasks: BackgroundTasks,
                              cache: client_utils.ClientCache[ClientOverviewCache] = Depends(OverviewCache),
                              query_params: QueryParams = Depends(get_query_params),
                              user: User = Depends(CurrentUser),
                              db: AsyncSession = Depends(get_db)):
    any_client = False
    if not query_params.client_ids:
        # query_params.client_ids = [None]
        any_client = True

    raw_overviews, non_cached = await cache.read(db)

    if non_cached:
        # All clients that weren't found in cache have to be read from DB
        clients = await client_utils.get_user_clients(
            user,
            None if any_client else non_cached,
            Client.transfers,
            Client.open_trades,
            db=db
        )
        for client in clients:
            daily = await db_all(
                client.daily_balance_stmt(
                    since=query_params.since,
                    to=query_params.to,
                ),
                session=db
            )

            overview = ClientOverviewCache(
                id=client.id,
                initial_balance=(
                    await client.get_exact_balance_at_time(query_params.since, db=db)
                    if query_params.since else
                    await client.initial(db)
                ),
                current_balance=(
                    await client.get_exact_balance_at_time(query_params.to, db=db)
                    if query_params.to else
                    await client.get_latest_balance(redis=redis, db=db)
                ),
                daily=daily,
                transfers=client.transfers,
                open_trades=client.open_trades
            )
            background_tasks.add_task(
                cache.write,
                client.id,
                overview,
            )
            raw_overviews.append(overview)

    ts1 = time.perf_counter()
    if raw_overviews:
        result: ClientOverview

        all_daily = []
        latest_by_client = {}

        by_day = groupby(
            sorted(itertools.chain.from_iterable(raw.daily for raw in raw_overviews), key=lambda b: b.time),
            lambda b: date_string(b.time)
        )

        for _, balances in by_day.items():
            present_ids = [
                balance.client_id for balance in balances
            ]
            present_excluded = [
                balance for client_id, balance in latest_by_client.items() if
                client_id not in present_ids
            ]

            current = sum_iter(balances)
            others = sum_iter(present_excluded) if present_excluded else None

            all_daily.append(
                (current + others) if others else current
            )
            for balance in balances:
                latest_by_client[balance.client_id] = balance

        all_transfers = sum_iter(overview.transfers for overview in raw_overviews)

        intervals = create_daily(
            all_daily,
            all_transfers,
            query_params.currency
        )

        overview = ClientOverview.construct(
            intervals=intervals,
            initial_balance=sum_iter(raw.initial_balance for raw in raw_overviews),
            current_balance=sum_iter(raw.current_balance for raw in raw_overviews if raw.current_balance),
            open_trades=sum_iter(o.open_trades for o in raw_overviews),
            transfers=all_transfers
        )

        encoded = jsonable_encoder(overview)
        ts2 = time.perf_counter()
        print('encode', ts2 - ts1)
        return CustomJSONResponse(content=encoded)
    else:
        return BadRequest('Invalid client id', 40000)


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

    if interval:
        stmt = performance_base_select.add_columns(
            func.date_trunc('day', TradeDB.open_time).label('date')
        ).group_by(
            # func.date_trunc('day', TradeDB.open_time).label('date')
            TradeDB.open_time
        )
    else:
        stmt = performance_base_select

    stmt = add_client_filters(
        stmt.where(
            time_range(TradeDB.open_time, query_params.since, query_params.to),
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


@router.get('/client/{client_id}', response_model=ClientDetailed)
async def get_client(client_id: int,
                     user: User = Depends(CurrentUser),
                     db: AsyncSession = Depends(get_db)):
    client = await client_utils.get_user_client(user,
                                                client_id,
                                                Client.trade_template,
                                                Client.events,
                                                db=db)

    if client:
        return ClientDetailed.from_orm(client)
    else:
        return NotFound('Invalid id')


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
