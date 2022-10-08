import time
from decimal import Decimal
from typing import List, Type, Union

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from pydantic import conlist
from sqlalchemy import select, delete, insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTasks

import api.utils.client as client_utils
from api.routers.template import query_templates
from database.models.document import DocumentModel
from api.dependencies import get_messenger, get_db, \
    FilterQueryParamsDep
from api.models.client import get_query_params
from api.models.trade import Trade, BasicTrade, DetailledTrade, UpdateTrade
from api.routers.label import add_trade_filters
from api.users import CurrentUser
from api.utils.responses import BadRequest, OK, CustomJSONResponse, ResponseModel
import utils
from database.dbasync import db_first, db_all
from database.dbmodels import TradeDB as TradeDB
from database.dbmodels.client import add_client_filters
from database.dbmodels.label import Label as LabelDB
from database.dbmodels.mixins.querymixin import QueryParams
from database.dbmodels.pnldata import PnlData
from database.dbmodels.trade import trade_association
from database.dbmodels.user import User
from database.models import BaseModel, OrmBaseModel, OutputID
from database.redis.client import ClientCacheKeys

router = APIRouter(
    tags=["trade"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


@router.patch('/trade/{trade_id}', response_model=DetailledTrade)
async def update_trade(trade_id: int,
                       body: UpdateTrade,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    trade = await db_first(
        add_trade_filters(select(TradeDB), user, trade_id),
        TradeDB.labels,
        session=db
    )

    if not trade:
        return BadRequest('Invalid Trade ID')

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
        template = await query_templates([body.template_id], user=user, session=db)
        trade.notes = DocumentModel(
            content=template.body,
            type='doc'
        )

    await db.commit()
    return DetailledTrade.from_orm(trade)


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

    @router.get(f'/{path}', response_model=ResponseModel[list[model]], **kwargs)
    async def get_trades(background_tasks: BackgroundTasks,
                         trade_id: list[int] = Query(None, alias='trade-id'),
                         cache: client_utils.ClientCache = Depends(TradeCache),
                         query_params: QueryParams = Depends(get_query_params),
                         filter_params: FilterQueryParams = Depends(FilterQueryParams),
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
            trade for trades in hits for trade in trades.data
            if all(f.check(trade) for f in filter_params)
        ]
        ts4 = time.perf_counter()
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
    TradeDB.labels,
    TradeDB.init_balance,
)


class PnlDataResponse(BaseModel):
    # Named Tuples are not supported (workaround with conlist)
    by_trade: dict[
        OutputID,
        list[conlist(Union[int, Decimal], min_items=3, max_items=3)]
    ]


@router.get('/trade-detailled/pnl-data',
            response_model=ResponseModel[PnlDataResponse])
async def get_pnl_data(trade_id: list[int] = Query(default=[], alias='trade-id'),
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    data: List[PnlData] = await db_all(
        add_client_filters(
            select(PnlData)
            .where(PnlData.trade_id.in_(trade_id) if trade_id else True)
            .join(PnlData.trade)
            .join(TradeDB.client)
            .order_by(PnlData.time),
            user=user
        ),
        session=db
    )

    result = {}
    for pnl_data in data:
        result.setdefault(str(pnl_data.trade_id), []).append(pnl_data.compact)

    return CustomJSONResponse(content={'by_trade': jsonable_encoder(result)})

