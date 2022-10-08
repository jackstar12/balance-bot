from __future__ import annotations
import asyncio
import logging
from datetime import datetime, date
from enum import Enum
from typing import List, Optional, Union, Literal, Any, TYPE_CHECKING
from uuid import UUID
import sqlalchemy as sa
import discord
import pytz
from aioredis import Redis
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, PickleType, or_, desc, asc, \
    Boolean, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, reconstructor

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm.dynamic import AppenderQuery
from sqlalchemy.sql import Select, Delete, Update
from sqlalchemy_utils.types.encrypted.encrypted_type import StringEncryptedType, FernetEngine

import os
import dotenv

import common.dbmodels.balance as db_balance
import common.utils as utils
from common.dbmodels.transfer import Transfer

from common.dbmodels.mixins.querymixin import QueryMixin
from common.dbmodels.mixins.editsmixin import EditsMixin
from common import customjson
from common.dbasync import db_first, db_all, db_select_all, redis, redis_bulk_keys, RedisKey, db_unique, \
    time_range
from common.dbmodels.chapter import Chapter
from common.dbmodels.discord.guild import Guild
from common.dbmodels.discord.guildassociation import GuildAssociation
from common.dbmodels.pnldata import PnlData
from common.dbmodels.mixins.serializer import Serializer
from common.dbmodels.user import User
from common.models.balance import Balance as BalanceModel, Amount
from common.dbsync import Base
from common.redis import TableNames
from common.dbmodels.trade import Trade
from common.redis.client import ClientSpace

if TYPE_CHECKING:
    from common.dbmodels import BalanceDB as Balance, Event

dotenv.load_dotenv()

_key = os.environ.get('ENCRYPTION_SECRET')
assert _key, 'Missing ENCRYPTION_SECRET in env'
from pydantic import BaseModel as PydanticBaseModel


class ClientRedis:

    def __init__(self, user_id: UUID, client_id: int, redis_instance: Redis = None):
        self.user_id = user_id
        self.client_id = client_id
        self.redis = redis_instance or redis

    async def redis_set(self, keys: dict[RedisKey, Any], space: Literal['cache', 'normal']):
        client_hash = self.cache_hash if space == 'cache' else self.normal_hash
        if space == 'cache':
            asyncio.ensure_future(self.redis.expire(client_hash, 5 * 60))
        keys[RedisKey(client_hash, self.user_id)] = str(self.user_id)

        mapping = {
            k.key: customjson.dumps(v.dict()) if isinstance(v, PydanticBaseModel) else v
            for k, v in keys.items()
        }
        logging.debug(f'Redis SET: {self} {mapping=}')
        return await self.redis.hset(client_hash, mapping=mapping)

    async def set_balance(self, balance: Balance):
        await self.redis_set(
            {
                RedisKey(TableNames.BALANCE): customjson.dumps(balance.serialize())
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

    async def set_last_exec(self, dt: datetime):
        await self.redis_set(
            keys={RedisKey(ClientSpace.LAST_EXEC): dt.timestamp()},
            space='normal'
        )

    #async def set_last_transfer(self, dt: datetime):
    #    await self.redis_set(
    #        keys={RedisKey(ClientSpace.LAST_EXEC): dt.timestamp()},
    #        space='normal'
    #    )

    @property
    def normal_hash(self):
        return utils.join_args(TableNames.USER, self.user_id, TableNames.CLIENT, self.client_id or '*')

    @property
    def cache_hash(self):
        return utils.join_args(TableNames.USER, self.user_id, TableNames.CLIENT, TableNames.CACHE,
                               self.client_id or '*')

    def __repr__(self):
        return f'<ClientRedis {self.client_id=} {self.user_id=}>'


class ClientType(Enum):
    BASIC = "basic"
    FULL = "full"


class ClientState(Enum):
    OK = "ok"
    SYNCHRONIZING = "synchronizing"
    ARCHIVED = "archived"
    INVALID = "invalid"


class Client(Base, Serializer, EditsMixin, QueryMixin):
    __tablename__ = TableNames.CLIENT.value
    __serializer_forbidden__ = ['api_secret']
    __serializer_data_forbidden__ = ['api_secret', 'discorduser']

    # Identification
    id = Column(Integer, primary_key=True)
    user_id = Column(GUID, ForeignKey('user.id', ondelete="CASCADE"), nullable=True)
    user = relationship('User', lazy='raise')
    # discord_user_id = Column(BigInteger, ForeignKey('discorduser.id', ondelete="CASCADE"), nullable=True)
    # discord_user = relationship('DiscordUser', lazy='raise')
    oauth_account_id = Column(ForeignKey('oauth_account.account_id', ondelete='SET NULL'), nullable=True)
    oauth_account = relationship('OAuthAccount', lazy='raise')

    # Properties
    api_key = Column(String(), nullable=False)
    api_secret = Column(StringEncryptedType(String(), _key.encode('utf-8'), FernetEngine), nullable=False)
    exchange = Column(String, nullable=False)
    subaccount = Column(String, nullable=True)
    extra_kwargs = Column(PickleType, nullable=True)
    currency = Column(String(10), default='USD')
    sandbox = Column(Boolean, default=False)

    # Data
    name = Column(String, nullable=True)
    rekt_on = Column(DateTime(timezone=True), nullable=True)
    type = Column(sa.Enum(ClientType), nullable=False, default=ClientType.BASIC)
    state = Column(sa.Enum(ClientState), nullable=False, default=ClientState.OK)

    trades: list[Trade] = relationship('Trade', lazy='raise',
                                       cascade="all, delete",
                                       back_populates='client',
                                       order_by="Trade.open_time")

    open_trades: list[Trade] = relationship('Trade', lazy='raise',
                                            back_populates='client',
                                            primaryjoin="and_(Trade.client_id == Client.id, Trade.open_qty > 0)",
                                            viewonly=True)

    history: AppenderQuery = relationship('Balance',
                                          back_populates='client',
                                          cascade="all, delete",
                                          lazy='dynamic',
                                          order_by='Balance.time',
                                          foreign_keys='Balance.client_id')

    # journals = relationship('Journal',
    #                        back_populates='client',
    #                        cascade="all, delete",
    #                        lazy='raise')

    transfers: list = relationship('Transfer', back_populates='client',
                             cascade='all, delete', lazy='raise')

    currently_realized_id = Column(ForeignKey('balance.id', ondelete='SET NULL'), nullable=True)
    currently_realized = relationship('Balance',
                                      lazy='joined',
                                      foreign_keys=currently_realized_id,
                                      cascade="all, delete",
                                      post_update=True)

    last_transfer_sync: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    last_execution_sync: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)

    @reconstructor
    def reconstructor(self):
        self.live_balance: Optional[Balance] = None

    @hybrid_property
    def invalid(self):
        return self.state == ClientState.INVALID

    @hybrid_property
    def archived(self):
        return self.state == ClientState.ARCHIVED

    @hybrid_property
    def discord_user(self):
        return self.user.discord_user if self.user else None

    def as_redis(self, redis_instance=None) -> ClientRedis:
        return ClientRedis(self.user_id, self.id, redis_instance=redis_instance)

    def validate(self):
        pass

    #nc def get_transfers

    async def calc_gain(self,
                        event: Event,
                        since: datetime,
                        db: AsyncSession,
                        currency: str = None):
        if event:
            since = max(since, event.start)

        balance_then = await self.get_exact_balance_at_time(since, db=db)
        balance_now = await self.get_latest_balance(redis=redis, db=db)
        transfered = await self.get_total_transfered(db=db, since=since, ccy=currency)

        if balance_then and balance_now:
            return balance_now.get_currency(currency).gain_since(
                balance_then.get_currency(currency),
                transfered
            )

    async def get_total_transfered(self,
                                   db: AsyncSession,
                                   ccy = None,
                                   since: datetime = None,
                                   to: datetime = None):
        stmt = select(
            func.sum(
                Transfer.amount if not ccy or ccy == self.currency else Transfer.extra_currencies[ccy]
            ).over(order_by=Transfer.id).label('total_transfered')
        ).where(
            Transfer.client_id == self.id,
            time_range(Transfer.time, since, to)
        )
        return await db_unique(stmt, session=db)

    async def get_latest_balance(self, redis: Redis, db: AsyncSession, currency=None) -> BalanceModel:
        live = await self.as_redis(redis).get_balance()
        if live:
            return live
        else:
            return BalanceModel.from_orm(await self.latest(db))

    def evaluate_balance(self):
        if not self.currently_realized:
            return
        realized = self.currently_realized.realized
        upnl = sum(trade.live_pnl.unrealized for trade in self.open_trades if trade.live_pnl)
        new = db_balance.Balance(
            realized=realized,
            unrealized=realized + upnl,
            time=datetime.now(pytz.utc),
            client=self
        )
        return new

    async def update_journals(self, current_balance: db_balance.Balance, today: date, db_session: AsyncSession):
        today = today or date.today()

        for journal in self.journals:
            if journal.current_chapter:
                end = getattr(journal.current_chapter, 'end_date', date.fromtimestamp(0))
                if today >= end:
                    latest = utils.list_last(self.recent_history)
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

    async def latest(self, db: AsyncSession):
        try:
            balance = db_balance.Balance

            return await db_first(
                select(balance).where(
                    balance.client_id == self.id
                ).order_by(
                    desc(db_balance.Balance.time)
                ),
                session=db
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

    @classmethod
    async def get_balance_at_time(cls, client_id: int, time: datetime, db: AsyncSession) -> Balance:
        DbBalance = db_balance.Balance
        stmt = select(DbBalance).where(
            DbBalance.time < time,
            DbBalance.client_id == client_id
        ).order_by(
            desc(DbBalance.time)
        )
        balance = await db_first(stmt, session=db)
        if not balance:
            balance = await db_first(
                select(DbBalance).where(
                    DbBalance.client_id == client_id
                ).order_by(DbBalance.time),
                session=db
            )
        return balance

    async def get_exact_balance_at_time(self, time: datetime, currency: str = None, db: AsyncSession = None) -> BalanceModel:
        balance = await self.get_balance_at_time(self.id, time, db)

        if self.is_premium and balance:
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

            pnl_data: list[PnlData] = await db_all(full_stmt, session=db)
            return db_balance.Balance(
                client_id=self.id,
                client=self,
                time=time,
                extra_currencies=[
                    Amount(
                        currency=amount.currency,
                        realized=amount.realized,
                        unrealized=amount.realized + sum(pnl.unrealized_ccy(amount.currency) for pnl in pnl_data),
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

    @hybrid_property
    def is_premium(self):
        return self.type == ClientType.FULL

    async def initial(self):
        try:
            if self.id:
                return await db_first(self.history.statement.order_by(asc(db_balance.Balance.time)))
        except ValueError:
            raise
            # return balance.Balance(amount=config.REGISTRATION_MINIMUM, currency='$', error=None, extra_kwargs={})

    def get_event_string(self):
        return ', '.join(
            event.name for event in self.events if event.is_active or event.is_free_for_registration()
        )

    async def get_discord_embed(self, guilds: Optional[List[Guild]] = None):

        embed = discord.Embed(title="User Information")

        def embed_add_value_safe(name, value, **kwargs):
            if value:
                embed.add_field(name=name, value=value, **kwargs)

        embed_add_value_safe('Events', self.get_event_string())
        embed_add_value_safe('Servers', await self.get_guilds_string(guilds), inline=False)
        embed.add_field(name='Exchange', value=self.exchange)
        embed.add_field(name='Api Key', value=self.api_key)

        if self.subaccount:
            embed.add_field(name='Subaccount', value=self.subaccount)
        for extra in self.extra_kwargs:
            embed.add_field(name=extra, value=self.extra_kwargs[extra])

        initial = await self.initial()
        if initial:
            embed.add_field(name='Initial Balance', value=initial.to_string())

        return embed

    def __hash__(self):
        return self.id.__hash__()


def add_client_filters(stmt: Union[Select, Delete, Update], user: User, client_ids: set[int] | list[int] = None) -> \
Union[
    Select, Delete, Update]:
    """
    Commonly used utility to add filters that ensure authorized client access
    :param stmt: stmt to add filters to
    :param user: desired user
    :param client_ids: possible client ids. If None, all clients will be used
    :return:
    """
    # user_checks = [Client.user_id == user.id]
    # if user.discord_user_id:
    #    user_checks.append(Client.discord_user_id == user.discord_user_id)
    return stmt.filter(
        Client.id.in_(client_ids) if client_ids else True,
        or_(
            Client.user_id == user.id,
            # Client.oauth_account_id == user.discord_user_id if user.discord_user_id else False
        )
    )
