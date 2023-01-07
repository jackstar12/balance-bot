import functools
import itertools
import logging
import operator
import time
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, Iterable

import aiohttp
import jwt
import pytz
from fastapi import APIRouter, Depends, Request, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select, asc, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTasks

import api.utils.client as client_utils
from database.dbmodels.transfer import Transfer as TransferDB
from api.models.trade import Trade, BasicTrade
from database.errors import InvalidClientError, ResponseError
from database.models.interval import Interval
from api.authenticator import Authenticator
from api.dependencies import get_authenticator, get_messenger, get_db, get_http_session
from api.models.client import ClientConfirm, ClientEdit, \
    ClientOverview, Transfer, ClientCreateBody, ClientInfo, ClientCreateResponse, get_query_params, ClientDetailed, \
    ClientOverviewCache
from api.settings import settings
from api.users import CurrentUser
from api.utils.responses import BadRequest, OK, CustomJSONResponse, NotFound, ResponseModel, InternalError
import core
from database.calc import create_daily
from database.dbasync import db_first, redis, async_maker, time_range, db_all, db_select_all
from database.dbmodels import TradeDB, BalanceDB, Execution
from database.dbmodels.client import Client, add_client_filters
from database.dbmodels.client import ClientQueryParams
from database.dbmodels.user import User
from database.enums import IntervalType
from common.exchanges import EXCHANGES
from common.exchanges.exchangeworker import ExchangeWorker
from database.models import OrmBaseModel, BaseModel, OutputID, InputID
from database.models.balance import Balance
from database.redis.client import ClientCacheKeys
from core.utils import validate_kwargs, groupby, date_string, sum_iter

router = APIRouter(
    tags=["client"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


@router.post('/client',
             response_model=ClientCreateResponse,
             dependencies=[Depends(CurrentUser)])
async def new_client(body: ClientCreateBody,
                     http_session: aiohttp.ClientSession = Depends(get_http_session)):
    try:
        exchange_cls = EXCHANGES[body.exchange]
        if issubclass(exchange_cls, ExchangeWorker):
            # Check if required keyword args are given
            if validate_kwargs(body.extra_kwargs or {}, exchange_cls.required_extra_args):
                client = body.get()

                try:
                    worker = exchange_cls(client, http_session, db_maker=async_maker)
                    init_balance = await worker.get_balance(date=datetime.now(pytz.utc))
                except InvalidClientError:
                    raise BadRequest('Invalid API credentials')
                except ResponseError:
                    raise InternalError()
                await worker.cleanup()

                if init_balance.error is None:
                    if init_balance.realized.is_zero():
                        raise BadRequest(
                            f'You do not have any balance in your account. Please fund your account before registering.'
                        )
                    else:
                        payload = jsonable_encoder(body)
                        payload['api_secret'] = client.api_secret
                        payload['exp'] = init_balance.time + timedelta(minutes=5)

                        return ClientCreateResponse(
                            token=jwt.encode(payload,
                                             settings.JWT_SECRET,
                                             algorithm='HS256'),
                            balance=Balance.from_orm(init_balance)
                        )
                else:
                    raise BadRequest(f'An error occured while getting your balance: {init_balance.error}.')
            else:
                logging.error(
                    f'Not enough kwargs for exchange {exchange_cls.exchange} were given.'
                    f'\nGot: {body.extra_kwargs}\nRequired: {exchange_cls.required_extra_args}'
                )
                args_readable = '\n'.join(exchange_cls.required_extra_args)
                raise BadRequest(
                    detail=f'Need more keyword arguments for exchange {exchange_cls.exchange}.'
                           f'\nRequirements:\n {args_readable}',
                    code=40100
                )
        else:
            logging.error(f'Class {exchange_cls} is no subclass of ClientWorker!')
    except KeyError:
        raise BadRequest(f'Exchange {body.exchange} unknown')


@router.post('/client/confirm', response_model=ClientInfo)
async def confirm_client(body: ClientConfirm,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    try:
        client_data = ClientCreateBody(
            **jwt.decode(body.token, settings.JWT_SECRET, algorithms=['HS256'])
        )
        client = client_data.get(user)

        db.add(client)
        await db.commit()
    except jwt.ExpiredSignatureError:
        raise BadRequest(detail='Token expired')
    except (jwt.InvalidTokenError, TypeError):
        raise BadRequest(detail='Invalid token')
    except IntegrityError:
        raise BadRequest(detail='This api key is already in use.')

    return ClientInfo.from_orm(client)


OverviewCache = client_utils.ClientCacheDependency(
    ClientCacheKeys.OVERVIEW,
    ClientOverviewCache
)


@router.get('/client/overview', response_model=ClientOverview)
async def get_client_overview(background_tasks: BackgroundTasks,
                              cache: client_utils.ClientCache[ClientOverviewCache] = Depends(OverviewCache),
                              query_params: ClientQueryParams = Depends(get_query_params),
                              user: User = Depends(CurrentUser),
                              db: AsyncSession = Depends(get_db)):
    any_client = False
    if not query_params.client_ids:
        # query_params.client_ids = [None]
        any_client = True

    if not query_params.currency:
        query_params.currency = 'USD'

    raw_overviews, non_cached = await cache.read(db)

    if non_cached:
        # All clients that weren't found in cache have to be read from DB
        clients = await client_utils.get_user_clients(
            user,
            None if any_client else non_cached,
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
            transfers = await db_all(
                select(TransferDB).where(
                    time_range(Execution.time, query_params.since, query_params.to),
                    TransferDB.client_id == client.id,
                    TransferDB.coin == query_params.currency
                ).join(TransferDB.execution),
                session=db
            )

            start_balance = await client.get_exact_balance_at_time(query_params.since)
            latest = await client.get_latest_balance(redis=redis)

            overview = ClientOverviewCache(
                id=client.id,
                total=Interval.create(
                    prev=start_balance.get_currency(query_params.currency),
                    current=latest.get_currency(query_params.currency),
                    offset=sum(transfer.size for transfer in transfers)
                ),
                daily_balance=daily,
                transfers=transfers,
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
            sorted(itertools.chain.from_iterable(raw.daily_balance for raw in raw_overviews), key=lambda b: b.time),
            lambda b: date_string(b.time)
        )

        for _, balances in by_day.items():
            present_ids = [balance.client_id for balance in balances]
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

        all_transfers = sorted(
            sum_iter(overview.transfers for overview in raw_overviews),
            key=lambda transfer: transfer.time
        )

        intervals = create_daily(
            all_daily,
            all_transfers,
            query_params.currency
        )

        query_params.limit = 5
        query_params.order = 'desc'
        recent_trades = await client_utils.query_trades(TradeDB.initial,
                                                        user_id=user.id,
                                                        query_params=query_params,
                                                        db=db)
        overview = ClientOverview.construct(
            intervals=intervals,
            total=sum_iter(raw.total for raw in raw_overviews),
            transfers=all_transfers,
            recent_trades=[BasicTrade.from_orm(trade) for trade in recent_trades]
        )

        encoded = jsonable_encoder(overview)
        ts2 = time.perf_counter()
        print('encode', ts2 - ts1)
        return CustomJSONResponse(content=encoded)
    else:
        raise BadRequest('Invalid client id', 40000)


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
                                 query_params: ClientQueryParams = Depends(get_query_params),
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
        user_id=user.id,
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
                             query_params: ClientQueryParams = Depends(get_query_params),
                             user: User = Depends(CurrentUser),
                             db: AsyncSession = Depends(get_db)):
    balance = await BalanceDB.query(
        time_col=BalanceDB.time,
        user_id=user.id,
        ids=balance_id,
        params=query_params,
        db=db
    )
    return Balance.from_orm(balance)


@router.get('/client/{client_id}', response_model=ClientDetailed)
async def get_client(client_id: InputID,
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
        raise NotFound('Invalid id')


@router.delete('/client/{client_id}')
async def delete_client(client_id: InputID,
                        user: User = Depends(CurrentUser),
                        db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        add_client_filters(delete(Client), user.id, {client_id}),
    )
    await db.commit()
    if result.rowcount == 1:
        return OK(detail='Success')
    else:
        raise NotFound(detail='Invalid ID')


@router.patch('/client/{client_id}', response_model=ClientDetailed)
async def update_client(client_id: InputID, body: ClientEdit,
                        user: User = Depends(CurrentUser),
                        db: AsyncSession = Depends(get_db)):
    client = await client_utils.get_user_client(user,
                                                client_id,
                                                Client.trade_template,
                                                Client.events,
                                                db=db)

    if client:
        for k, v in body.dict(exclude_none=True).items():
            setattr(client, k, v)

        client.validate()
    else:
        raise BadRequest('Invalid client id')

    await db.commit()
    return ClientDetailed.from_orm(client)
