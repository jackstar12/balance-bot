from __future__ import annotations
import asyncio
import logging
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Optional, Union, Literal, Any, TYPE_CHECKING, NamedTuple
from uuid import UUID
import sqlalchemy as sa
import pytz
from aioredis import Redis
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, PickleType, or_, desc, Boolean, select, func, \
    Date, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, reconstructor, RelationshipProperty

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm.dynamic import AppenderQuery
from sqlalchemy.sql import Select, Delete, Update
from sqlalchemy_utils.types.encrypted.encrypted_type import StringEncryptedType, FernetEngine

import os
import dotenv

import database.dbmodels as dbmodels
import core
from database.enums import MarketType
from database.env import ENV
from database.errors import UserInputError
from database.dbmodels.transfer import Transfer

from database.dbmodels.mixins.editsmixin import EditsMixin
from core import json as customjson, safe_cmp, utc_now
from database.dbasync import db_first, db_all, db_select_all, redis, redis_bulk_keys, RedisKey, db_unique, \
    time_range, safe_op, safe_eq
from database.dbmodels.editing.chapter import Chapter
from database.dbmodels.discord.guildassociation import GuildAssociation
from database.dbmodels.pnldata import PnlData
from database.dbmodels.mixins.serializer import Serializer
from database.dbmodels.user import User
from database.models import BaseModel, InputID
from database.models.balance import Balance as BalanceModel, Amount
from database.dbsync import Base, BaseMixin
from database.models.eventinfo import EventState
from database.redis import TableNames
from database.dbmodels.trade import Trade
from database.redis.client import ClientSpace

if TYPE_CHECKING:
    from database.dbmodels import BalanceDB as Balance, Event

from pydantic import BaseModel as PydanticBaseModel, Field


class ExchangeInfo(NamedTuple):
    name: str
    sandbox: bool


class ClientRedis:

    def __init__(self, user_id: UUID, client_id: int, redis_instance: Redis = None):
        self.user_id = user_id
        self.id = client_id
        self.redis = redis_instance or redis

    async def redis_set(self, keys: dict[RedisKey, Any], space: Literal['cache', 'normal']):
        client_hash = self.cache_hash if space == 'cache' else self.normal_hash
        if space == 'cache':
            asyncio.ensure_future(self.redis.expire(client_hash, 5 * 60))
        # keys[RedisKey(client_hash, self.user_id)] = str(self.user_id)

        mapping = {
            k.key: customjson.dumps(v.dict()) if isinstance(v, PydanticBaseModel) else v
            for k, v in keys.items()
        }
        logging.debug(f'Redis SET: {self} {mapping=}')
        return await self.redis.hset(client_hash, mapping=mapping)

    async def set_balance(self, balance: Balance):
        await self.redis_set(
            {
                RedisKey(TableNames.BALANCE): customjson.dumps(
                    BalanceModel.from_orm(balance).dict()
                )
            },
            space='normal'
        )

    async def get_balance(self) -> BalanceModel:
        raw = await self.redis.hget(self.normal_hash, key=str(TableNames.BALANCE.value))
        if raw:
            as_json = customjson.loads(raw)
            return BalanceModel(**as_json)

    async def read_cache(self, *keys: RedisKey):
        """
        Class Method so that there's no need for an actual DB instance
        (useful when reading cache)
        """
        return await redis_bulk_keys(
            self.cache_hash, *keys, redis_instance=self.redis
        )

    async def invalidate_cache(self):
        return await self.redis.delete(self.cache_hash)

    async def set_last_exec(self, dt: datetime):
        await self.redis_set(
            keys={RedisKey(ClientSpace.LAST_EXEC): dt.timestamp()},
            space='normal'
        )

    # async def set_last_transfer(self, dt: datetime):
    #    await self.redis_set(
    #        keys={RedisKey(ClientSpace.LAST_EXEC): dt.timestamp()},
    #        space='normal'
    #    )

    @property
    def normal_hash(self):
        return core.join_args(TableNames.USER, self.user_id, TableNames.CLIENT, self.id or '*')

    @property
    def cache_hash(self):
        return core.join_args(TableNames.USER, self.user_id, TableNames.CLIENT, TableNames.CACHE,
                              self.id or '*')

    def __repr__(self):
        return f'<ClientRedis {self.id=} {self.user_id=}>'


class ClientType(Enum):
    BASIC = "basic"
    FULL = "full"


class ClientState(Enum):
    OK = "ok"
    SYNCHRONIZING = "synchronizing"
    ARCHIVED = "archived"
    INVALID = "invalid"


class QueryParams(BaseModel):
    since: Optional[datetime] = Field(default_factory=lambda: datetime.fromtimestamp(0, pytz.utc))
    to: Optional[datetime]
    limit: Optional[int]
    offset: Optional[int]
    order: Optional[Literal['desc', 'asc']]

    def within(self, other: QueryParams):
        return (
                (not other.since or (self.since and self.since >= other.since))
                and
                (not other.to or (self.to and self.to < other.to))
        )


class ClientQueryParams(QueryParams):
    client_ids: Optional[set[InputID]]
    currency: Optional[str]

    def within(self, other: ClientQueryParams):
        return super().within(other) and self.currency == other.currency


class ClientQueryMixin:
    client: RelationshipProperty

    @classmethod
    async def query(cls,
                    *eager,
                    time_col: Column,
                    user_id: UUID,
                    ids: list[int] | None,
                    params: ClientQueryParams,
                    db: AsyncSession) -> list[Self]:
        return await db_all(
            add_client_checks(
                select(cls).filter(
                    cls.id.in_(ids) if ids else True,
                    time_range(time_col, params.since, params.to)
                ).join(
                    cls.client
                ).limit(
                    params.limit
                ),
                user_id=user_id,
                client_ids=params.client_ids
            ),
            *eager,
            session=db
        )


class Client(Base, Serializer, BaseMixin, EditsMixin, ClientQueryMixin):
    __tablename__ = TableNames.CLIENT.value
    __serializer_forbidden__ = ['api_secret']
    __serializer_data_forbidden__ = ['api_secret', 'discorduser']

    # Identification
    id = Column(Integer, primary_key=True)

    user_id = Column(GUID, ForeignKey('user.id', ondelete="CASCADE"), nullable=True)
    user = relationship('User', lazy='raise')

    oauth_account_id = Column(ForeignKey('oauth_account.account_id', ondelete='SET NULL'), nullable=True)
    oauth_account = relationship('OAuthAccount', lazy='raise')

    # Properties
    api_key = Column(String(), nullable=False)
    api_secret = Column(
        StringEncryptedType(String(), ENV.ENCRYPTION.get_secret_value().encode('utf-8'), FernetEngine),
        nullable=False
    )
    exchange = Column(String, nullable=False)
    subaccount = Column(String, nullable=True)
    extra_kwargs = Column(PickleType, nullable=True)
    currency = Column(String(10), default='USD')
    sandbox = Column(Boolean, default=False)

    # Data
    name = Column(String, nullable=True)
    type = Column(sa.Enum(ClientType), nullable=False, default=ClientType.BASIC)
    state = Column(sa.Enum(ClientState), nullable=False, default=ClientState.OK)

    trades: list[Trade] = relationship('Trade', lazy='raise',
                                       back_populates='client',
                                       order_by="Trade.open_time")

    open_trades: list[Trade] = relationship('Trade', lazy='raise',
                                            back_populates='client',
                                            primaryjoin="and_(Trade.client_id == Client.id, Trade.open_qty > 0)",
                                            viewonly=True)

    history: AppenderQuery = relationship('Balance',
                                          back_populates='client',
                                          lazy='dynamic',
                                          order_by='Balance.time',
                                          foreign_keys='Balance.client_id')

    transfers: list = relationship('Transfer', back_populates='client', lazy='raise')

    currently_realized_id = Column(ForeignKey('balance.id', ondelete='SET NULL'), nullable=True)
    currently_realized: Balance = relationship('Balance',
                                               lazy='joined',
                                               foreign_keys=currently_realized_id,
                                               post_update=True)

    trade_template_id = Column(ForeignKey('template.id', ondelete='SET NULL'), nullable=True)
    trade_template = relationship('Template', lazy='raise', foreign_keys=trade_template_id)

    last_transfer_sync: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    last_execution_sync: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)

    __tableargs__ = (
        UniqueConstraint(user_id, exchange, api_key),
    )

    @property
    def exchange_info(self):
        return ExchangeInfo(name=self.exchange, sandbox=self.sandbox)

    @reconstructor
    def reconstructor(self):
        self.live_balance: Optional[Balance] = None

    @hybrid_property
    def invalid(self):
        return self.state == ClientState.INVALID

    @hybrid_property
    def archived(self):
        return self.state == ClientState.ARCHIVED

    def as_redis(self, redis_instance=None) -> ClientRedis:
        return ClientRedis(self.user_id, self.id, redis_instance=redis_instance)

    def validate(self):
        pass

    async def calc_gain(self,
                        event: Event,
                        since: datetime | Balance,
                        currency: str = None):
        if isinstance(since, datetime):
            if event:
                since = max(since, event.start)
            balance_then = await self.get_exact_balance_at_time(since)
        else:
            balance_then = since

        balance_now = await self.get_latest_balance(redis=redis)

        if balance_then and balance_now:
            transfered = await self.get_total_transfered(since=balance_then.time, ccy=currency)
            return balance_now.get_currency(currency).gain_since(
                balance_then.get_currency(currency),
                transfered
            )

    def daily_balance_stmt(self,
                           amount: int = None,
                           since: datetime = None,
                           to: datetime = None):
        now = core.utc_now()

        since = since or datetime.fromtimestamp(0, pytz.utc)
        to = to or now

        since_date = since.replace(tzinfo=pytz.UTC).replace(hour=0, minute=0, second=0)
        daily_end = min(now, to)

        if amount:
            try:
                daily_start = daily_end - timedelta(days=amount - 1)
            except OverflowError:
                raise UserInputError('Invalid daily amount given')
        else:
            daily_start = since_date

        # We always want to fetch the last balance of the date (first balance of next date),
        # so we need to partition by the current date and order by
        # time in descending order so that we can pick out the first (last) one

        sub = select(
            func.row_number().over(
                order_by=desc(dbmodels.Balance.time),
                partition_by=dbmodels.Balance.time.cast(Date)
            ).label('row_number'),
            dbmodels.Balance.id.label('id')
        ).filter(
            dbmodels.Balance.client_id == self.id,
            dbmodels.Balance.time > daily_start
        ).subquery()

        return select(
            dbmodels.Balance,
            sub
        ).filter(
            sub.c.row_number == 1,
            dbmodels.Balance.id == sub.c.id
        ).order_by(
            dbmodels.Balance.time
        )

    @classmethod
    async def get_total_transfered(cls,
                                   client_ids: list[int],
                                   user_id: UUID,
                                   ccy=None,
                                   since: datetime = None,
                                   to: datetime = None,
                                   db: AsyncSession = None):
        stmt = add_client_checks(
            select(
                func.sum(
                    dbmodels.Execution.effective_size if not ccy else dbmodels.Execution.effective_qty
                ).label('total_transfered')
            ).join(Transfer.execution).where(
                time_range(dbmodels.Execution.time, since, to),
                safe_eq(Transfer.coin, ccy)
            ),
            user_id,
            client_ids,
        )
        return await db_unique(stmt, session=db)

    async def get_latest_balance(self, redis: Redis, currency=None) -> BalanceModel | None:
        live = await self.as_redis(redis).get_balance()
        if live:
            if not live.currency:
                live.currency = self.currency
            return live
        else:
            latest = await self.latest()
            return BalanceModel.from_orm(latest) if latest else None

    def evaluate_balance(self):
        if not self.currently_realized:
            return

        result = self.currently_realized.clone()
        result.time = utc_now()

        for trade in self.open_trades:
            if trade.initial.market_type == MarketType.DERIVATIVES and trade.live_pnl:
                result.add_amount(trade.settle, unrealized=trade.live_pnl.unrealized)

        return result

    async def update_journals(self, current_balance: dbmodels.Balance, today: date, db_session: AsyncSession):
        today = today or date.today()

        for journal in self.journals:
            if journal.current_chapter:
                end = getattr(journal.current_chapter, 'end_date', date.fromtimestamp(0))
                if today >= end:
                    latest = core.list_last(self.recent_history)
                    if latest:
                        journal.current_chapter.end_balance = latest
                        new_chapter = Chapter(
                            start_date=today,
                            end_date=today + journal.chapter_interval,
                            balances=[latest]
                        )
                        journal.current_chapter = new_chapter
                        db_session.add(new_chapter)
                elif journal.current_chapter:
                    contained = 0
                    for index, balance in enumerate(journal.current_chapter.balances):
                        if balance.client_id == self.id:
                            contained += 1
                            if contained == 2:
                                journal.current_chapter.balances[index] = current_balance
                    if contained < 2:
                        journal.current_chapter.balances.append(current_balance)

        await db_session.commit()

    async def latest(self):
        try:
            balance = dbmodels.Balance

            return await db_first(
                select(balance).where(
                    balance.client_id == self.id
                ).order_by(
                    desc(dbmodels.Balance.time)
                ),
                session=self.async_session
            )
        except ValueError:
            return None

    async def is_global(self, guild_id: int = None):
        if self.discord_user_id:
            if guild_id:
                associations = await db_select_all(GuildAssociation, discord_user_id=self.discord_user_id,
                                                   client_id=self.id, guild_id=guild_id)
            else:
                associations = await db_select_all(GuildAssociation, discord_user_id=self.discord_user_id,
                                                   client_id=self.id)
            return bool(associations)
        elif self.user_id:
            return True

    async def get_balance_at_time(self, time: datetime) -> Balance:
        DbBalance = dbmodels.Balance
        balance = None
        if time:
            stmt = select(DbBalance).where(
                DbBalance.time < time,
                DbBalance.client_id == self.id
            ).order_by(
                desc(DbBalance.time)
            )
            balance = await db_first(stmt, session=self.async_session)
        if not balance:
            balance = await self.initial()
        return balance

    async def get_exact_balance_at_time(self, time: datetime, currency: str = None) -> Balance:
        balance = await self.get_balance_at_time(time)

        if self.type == ClientType.FULL and balance and time and False:
            # Probably the most beautiful query I've ever written
            subq = select(
                PnlData.id.label('pnl_id'),
                func.row_number().over(
                    order_by=desc(PnlData.time), partition_by=Trade.symbol
                ).label('row_number')
            ).join(
                PnlData.trade
            ).filter(
                PnlData.time > balance.time,
                PnlData.time < time,
                Trade.open_time <= time,
                Trade.client_id == self.id
            ).subquery()

            full_stmt = select(
                PnlData
            ).filter(
                PnlData.id == subq.c.pnl_id,
                Trade.open_time <= time,
                subq.c.row_number <= 1
            )

            pnl_data: list[PnlData] = await db_all(full_stmt, session=self.async_session)

            return dbmodels.Balance(
                client_id=self.id,
                client=self,
                time=time,
                extra_currencies=[
                    Amount(
                        currency=amount.currency,
                        realized=amount.realized,
                        # unrealized=amount.realized + sum(pnl.unrealized_ccy(amount.currency) for pnl in pnl_data),
                        time=time
                    )
                    for amount in balance.extra_currencies
                ],
                realized=balance.realized,
                unrealized=balance.realized + sum(pnl.unrealized for pnl in pnl_data)
            )

        else:
            return balance

    @hybrid_property
    def is_active(self):
        return not all(not event.is_active for event in self.events)

    async def initial(self):
        b = dbmodels.Balance
        return await db_first(
            select(b).where(
                b.client_id == self.id
            ).order_by(
                b.time
            ),
            session=self.async_session
        )

    def get_event_string(self):
        return ', '.join(
            event.name for event in self.events if event.is_(EventState.ACTIVE) or event.is_(EventState.REGISTRATION)
        )

    def __hash__(self):
        return self.id.__hash__()


def add_client_checks(stmt: Union[Select, Delete, Update], user_id: UUID,
                      client_ids: set[int] | list[int] = None,
                      currency: str = None) -> Union[Select, Delete, Update]:
    """
    Commonly used utility to add filters that ensure authorized client access
    :param currency:
    :param stmt: stmt to add filters to
    :param user_id: desired user
    :param client_ids: possible client ids. If None, all clients will be used
    :return:
    """
    # user_checks = [Client.user_id == user.id]
    # if user.discord_user_id:
    #    user_checks.append(Client.discord_user_id == user.discord_user_id)
    return stmt.where(
        Client.id.in_(client_ids) if client_ids else True,
        Client.user_id == user_id,
        safe_op(Client.currency, currency)
        # Client.type == ClientType.FULL,
        # Client.state.not_in((ClientState.INVALID, ClientState.SYNCHRONIZING)),
    )
