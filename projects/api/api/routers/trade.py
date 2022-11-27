import asyncio
import operator
import time
from datetime import datetime
from decimal import Decimal
from typing import List, Type, Union, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from pydantic import conlist
from sqlalchemy import select, delete, insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTasks

import core
import api.utils.client as client_utils
from database.dbmodels.mixins.filtermixin import FilterParam
from api.routers.template import query_templates
from core import join_args, json, groupby
from core.json import dumps
from database.dbmodels.authgrant import AuthGrant, TradeGrant, AssociationType, ChapterGrant
from database.models.document import DocumentModel, Operator
from api.dependencies import get_messenger, get_db, \
    FilterQueryParamsDep
from api.models.client import get_query_params
from api.models.trade import Trade, BasicTrade, DetailledTrade, UpdateTrade, UpdateTradeResponse
from api.users import CurrentUser, get_auth_grant_dependency, DefaultGrant
from api.utils.responses import BadRequest, OK, CustomJSONResponse, ResponseModel, Unauthorized
from database.dbasync import db_first, db_all, redis_bulk, redis
from database.dbmodels import TradeDB as TradeDB, Chapter, Balance
from database.dbmodels.client import add_client_filters, QueryParams
from database.dbmodels.label import Label as LabelDB
from database.dbmodels.client import ClientQueryParams
from database.dbmodels.pnldata import PnlData
from database.dbmodels.trade import trade_association
from database.dbmodels.user import User
from database.models import BaseModel, OrmBaseModel, OutputID, InputID
from database.redis.client import ClientCacheKeys

router = APIRouter(
    tags=["trade"],
    dependencies=[Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


def add_trade_filters(stmt, user_id: UUID, trade_id: int):
    return add_client_filters(
        stmt.filter(
            TradeDB.id == trade_id,
        ).join(TradeDB.client),
        user_id
    )


@router.patch('/trade/{trade_id}', response_model=UpdateTradeResponse)
async def update_trade(trade_id: InputID,
                       body: UpdateTrade,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    trade = await db_first(
        add_trade_filters(select(TradeDB), user.id, trade_id),
        TradeDB.labels,
        session=db
    )

    if not trade:
        raise BadRequest('Invalid Trade ID')

    if body.notes:
        trade.notes = body.notes

    if body.labels:
        added = body.labels.label_ids - set(label.id for label in trade.labels)
        for label_id in added:
            await db.execute(
                insert(trade_association).values(
                    trade_id=trade_id,
                    label_id=label_id
                ),
            )

        await db.execute(
            delete(trade_association).where(
                LabelDB.id == trade_association.c.label_id,
                LabelDB.group_id.in_(body.labels.group_ids),
                ~LabelDB.id.in_(body.labels.label_ids)
            ),
        )

    if body.template_id:
        template = await query_templates([body.template_id], user_id=user.id, session=db)
        trade.notes = DocumentModel(
            content=template.body,
            type='doc'
        )

    await db.commit()
    return UpdateTradeResponse(
        label_ids=body.labels and trade.label_ids,
        notes=body.template_id and trade.notes
    )


auth = get_auth_grant_dependency(ChapterGrant)


class TradeQueryParams(ClientQueryParams):
    trade_ids: set[int]

    def within(self, other: 'TradeQueryParams'):
        return other and super().within(other) and self.trade_ids.issubset(other.trade_ids)


def get_trade_params(client_id: set[InputID] = Query(default=[]),
                     trade_id: set[InputID] = Query(default=[], alias='id'),
                     currency: str = Query(default=None),
                     since: datetime = Query(default=None),
                     to: datetime = Query(default=None),
                     order: Literal['asc', 'desc'] = Query(default='asc')):
    return TradeQueryParams(
        client_ids=client_id,
        trade_ids=trade_id,
        currency=currency,
        since=since,
        to=to,
        order=order
    )


def create_trade_endpoint(path: str,
                          model: Type[BasicTrade],
                          *eager,
                          **kwargs):

    class Trades(BaseModel):
        data: list[model]

    TradeCache = client_utils.ClientCacheDependency(
        core.join_args(ClientCacheKeys.TRADE, path),
        Trades,
        auth,
        get_trade_params
    )

    FilterQueryParams = FilterQueryParamsDep(TradeDB, model)

    @router.get(f'/{path}', response_model=list[model], **kwargs)
    async def get_trades(background_tasks: BackgroundTasks,
                         chapter_id: InputID = Query(default=None),
                         cache: client_utils.ClientCache = Depends(TradeCache),
                         query_params: TradeQueryParams = Depends(get_trade_params),
                         filter_params: FilterQueryParams = Depends(FilterQueryParams),
                         grant: AuthGrant = Depends(auth),
                         db: AsyncSession = Depends(get_db)):
        ts1 = time.perf_counter()

        if not grant.is_root_for(AssociationType.TRADE):
            if chapter_id:
                node = await db_first(Chapter.query_nodes(chapter_id, query_params), session=db)
                if not node:
                    raise Unauthorized()
            else:
                trade_id = await grant.check_ids(AssociationType.TRADE, query_params.trade_ids)
                if not trade_id:
                    return OK(result=[])

        hits, misses = await cache.read(db)

        if query_params.trade_ids:
            filter_params.append(
                FilterParam.construct(field='id', values=list(map(str, query_params.trade_ids)), op=Operator.EQ)
            )

        if query_params.currency:
            filter_params.append(
                FilterParam.construct(field='settle', values=[query_params.currency], op=Operator.EQ)
            )

        if misses:
            query_params.client_ids = misses

            trades_db = await client_utils.query_trades(
                *eager,
                user_id=grant.user_id,
                query_params=query_params,
                trade_ids=query_params.trade_ids,
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


        ts4 = time.perf_counter()
        return OK(
            result=[
                trade for trades in hits for trade in trades.data
                if all(f.check(trade) for f in filter_params)
            ]
        )


create_trade_endpoint(
    'trade-overview',
    BasicTrade,
    TradeDB.executions
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
    TradeDB.labels,
    (TradeDB.init_balance, Balance.extra_currencies),
)


class PnlDataResponse(BaseModel):
    # Named Tuples are not supported (workaround with conlist)
    by_trade: dict[
        OutputID,
        list[conlist(Union[int, Decimal], min_items=3, max_items=3)]
    ]


@router.get('/trade-detailled/pnl-data',
            response_model=ResponseModel[PnlDataResponse])
async def get_pnl_data(trade_id: list[InputID] = Query(default=[]),
                       chapter_id: InputID = Query(default=None),
                       grant: AuthGrant = Depends(auth),
                       db: AsyncSession = Depends(get_db)):
    if not grant.is_root_for(AssociationType.TRADE):
        if chapter_id:
            node = await db_first(Chapter.query_nodes(chapter_id, None), session=db)
            if not node:
                raise Unauthorized()
        else:
            trade_id = await grant.check_ids(AssociationType.TRADE, trade_id)
            if not trade_id:
                return OK(result=[])

    data: List[PnlData] = await db_all(
        add_client_filters(
            select(PnlData)
            .where(PnlData.trade_id.in_(trade_id) if trade_id else True)
            .join(PnlData.trade)
            .join(TradeDB.client)
            .order_by(PnlData.time),
            user_id=grant.user_id
        ),
        session=db
    )

    result = {}
    for pnl_data in data:
        result.setdefault(str(pnl_data.trade_id), []).append(pnl_data.compact)

    return CustomJSONResponse(content={'by_trade': jsonable_encoder(result)})
