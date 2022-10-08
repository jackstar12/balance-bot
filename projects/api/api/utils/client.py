import dataclasses
import time
from decimal import Decimal
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select, Column

from datetime import datetime
from typing import Optional, Dict, List, Mapping, Any, Type, TypeVar, Generic, Awaitable
from collections import OrderedDict

import pytz
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_user_id
from api.models.client import get_query_params
from database.dbmodels.mixins.querymixin import QueryParams
from database.models import BaseModel
from database.redis.client import ClientSpace, ClientCacheKeys
from database.dbmodels import TradeDB
from database.dbasync import redis, db_all, redis_bulk, RedisKey, db_first
from database.dbmodels.balance import Balance
from database.dbmodels.client import Client, add_client_filters, ClientRedis
from database.dbmodels.user import User


def ratio(a: float, b: float):
    return round(a / (a + b), ndigits=3) if a + b > 0 else 0.5


def update_dicts(*dicts: Dict, **kwargs):
    for arg in dicts:
        arg.update(kwargs)


def get_dec(mapping: Mapping, key: Any, default: Any):
    return Decimal(mapping.get(key, default))


T = TypeVar('T', bound=BaseModel)


def _parse_date(val: bytes) -> datetime:
    ts = float(val)
    return datetime.fromtimestamp(ts, pytz.utc)


@dataclasses.dataclass
class ClientCache(Generic[T]):
    cache_data_key: ClientCacheKeys
    data_model: Type[T]
    query_params: QueryParams
    user_id: UUID
    client_last_exec: dict[int, datetime] = dataclasses.field(default_factory=lambda: {})

    async def read(self, db: AsyncSession) -> tuple[list[T], list[int]]:
        pairs = OrderedDict()

        if not self.query_params.client_ids:
            self.query_params.client_ids = await db_all(
                select(Client.id).filter(
                    Client.user_id == self.user_id
                ),
                session=db
            )

        for client_id in self.query_params.client_ids:
            client = ClientRedis(self.user_id, client_id)
            pairs[client.normal_hash] = [
                RedisKey(ClientSpace.LAST_EXEC, parse=_parse_date)
            ]
            pairs[client.cache_hash] = [
                RedisKey(self.cache_data_key, ClientSpace.LAST_EXEC, parse=_parse_date),
                RedisKey(self.cache_data_key, ClientSpace.QUERY_PARAMS, model=QueryParams)
            ]

        data = await redis_bulk(pairs, redis_instance=redis)

        hits = []
        misses = []

        for client_id in self.query_params.client_ids:
            client = ClientRedis(self.user_id, client_id)

            last_exec = data[client.normal_hash][0]
            cached_last_exec = data[client.cache_hash][0]
            cached_query_params: QueryParams = data[client.cache_hash][1]

            if last_exec and False:
                self.client_last_exec[client_id] = last_exec

                if (
                        cached_last_exec and cached_last_exec >= last_exec
                        and self.query_params.within(cached_query_params)
                ):
                    ts1 = time.perf_counter()
                    raw_overview, = await client.read_cache(
                        RedisKey(self.cache_data_key, model=self.data_model),
                    )
                    ts2 = time.perf_counter()
                    print('Reading Cache', ts2 - ts1)
                    if raw_overview:
                        hits.append(raw_overview)
                    else:
                        misses.append(client_id)
                else:
                    misses.append(client_id)
            else:
                misses.append(client_id)

        return hits, misses

    async def write(self, client_id: int, data: T):
        last_exec = self.client_last_exec.get(client_id) or 0
        return await ClientRedis(self.user_id, client_id).redis_set(
            keys={
                RedisKey(self.cache_data_key): data,
                RedisKey(self.cache_data_key, ClientSpace.LAST_EXEC): last_exec.timestamp() if last_exec else 0,
                RedisKey(self.cache_data_key, ClientSpace.QUERY_PARAMS): self.query_params
            },
            space='cache'
        )


class ClientCacheDependency:

    def __init__(self,
                 cache_data_key: ClientCacheKeys,
                 data_model: Type[BaseModel], ):
        self.cache_data_key = cache_data_key
        self.data_model = data_model

    def __call__(self, query_params: QueryParams = Depends(get_query_params),
                 user_id: UUID = Depends(get_user_id)):
        return ClientCache(
            cache_data_key=self.cache_data_key,
            data_model=self.data_model,
            query_params=query_params,
            user_id=user_id
        )


TTable = TypeVar('TTable')


async def query_table(*eager,
                      table: TTable,
                      time_col: Column,
                      user: User,
                      ids: List[int],
                      query_params: QueryParams,
                      db: AsyncSession) -> list[TTable]:
    return await db_all(
        add_client_filters(
            select(table).filter(
                table.id.in_(ids) if ids else True,
                time_col >= query_params.since if query_params.since else True,
                time_col <= query_params.to if query_params.to else True
            ).join(
                table.client
            ).limit(
                query_params.limit
            ),
            user=user,
            client_ids=query_params.client_ids
        ),
        *eager,
        session=db
    )


def query_trades(*eager,
                 user: User,
                 trade_id: List[int],
                 query_params: QueryParams,
                 db: AsyncSession):
    return query_table(
        *eager,
        table=TradeDB,
        time_col=TradeDB.open_time,
        user=user,
        ids=trade_id,
        query_params=query_params,
        db=db
    )

    # return db_all(
    #    add_client_filters(
    #        select(TradeDB).filter(
    #            TradeDB.id.in_(trade_id) if trade_id else True,
    #            TradeDB.open_time >= query_params.since if query_params.since else True,
    #            TradeDB.open_time <= query_params.to if query_params.to else True
    #        ).join(
    #            TradeDB.client
    #        ).limit(
    #            query_params.limit
    #        ),
    #        user=user,
    #        client_ids=query_params.client_ids
    #    ),
    #    *eager,
    #    session=db
    # )


def query_balance(*eager,
                  user: User,
                  balance_id: List[int],
                  query_params: QueryParams,
                  db: AsyncSession):
    return query_table(*eager,
                       table=Balance, time_col=Balance.time, user=user,
                       ids=balance_id, query_params=query_params, db=db)
    # return db_all(
    #     add_client_filters(
    #         select(Balance).filter(
    #             Balance.id.in_(balance_id) if balance_id else True,
    #             Balance.time >= query_params.since if query_params.since else True,
    #             Balance.time <= query_params.to if query_params.to else True
    #         ).join(
    #             Balance.client
    #         ).limit(
    #             query_params.limit
    #         ),
    #         user=user,
    #         client_ids=query_params.client_ids
    #     ),
    #     *eager,
    #     session=db
    # )


def get_user_client(user: User, client_id: int, *eager, db: AsyncSession = None) -> Awaitable[Optional[Client]]:
    return db_first(
        add_client_filters(select(Client), user, {client_id}),
        *eager,
        session=db
    )


def get_user_clients(user: User, ids: List[int] = None, *eager, db: AsyncSession = None) -> Awaitable[list[Client]]:
    return db_all(
        add_client_filters(select(Client), user, ids), *eager, session=db
    )
