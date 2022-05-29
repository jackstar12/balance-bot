import json
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import List, Optional, Union, TYPE_CHECKING
import discord
import pytz
from aioredis import Redis
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, PickleType, BigInteger, or_, desc, asc, \
    Boolean, select, func, subquery, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, aliased

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm.dynamic import AppenderQuery
from sqlalchemy.sql import Select, Delete, Update
from sqlalchemy_utils.types.encrypted.encrypted_type import StringEncryptedType, FernetEngine

import os
import dotenv

from balancebot.common import customjson
from balancebot.common.database_async import db_first, db_all, db_select_all
import balancebot.common.dbmodels.balance as db_balance
from balancebot.common.dbmodels.chapter import Chapter
from balancebot.common.dbmodels.execution import Execution
from balancebot.common.dbmodels.guild import Guild
from balancebot.common.dbmodels.guildassociation import GuildAssociation
from balancebot.common.dbmodels.journal import Journal
from balancebot.common.dbmodels.pnldata import PnlData
from balancebot.common.dbmodels.serializer import Serializer
from balancebot.common.dbmodels.user import User
from balancebot.common.database import Base
import balancebot.common.utils as utils
from balancebot.common.messenger import NameSpace

from balancebot.common.dbmodels.trade import Trade

dotenv.load_dotenv()

_key = os.environ.get('ENCRYPTION_SECRET')
assert _key, 'Missing ENCRYPTION_SECRET in env'


class Client(Base, Serializer):
    __tablename__ = 'client'
    __serializer_forbidden__ = ['api_secret']
    __serializer_data_forbidden__ = ['api_secret', 'discorduser']

    # Identification
    id = Column(Integer, primary_key=True)
    user_id = Column(GUID, ForeignKey('user.id', ondelete="CASCADE"), nullable=True)
    user = relationship('User', lazy='noload')
    discord_user_id = Column(BigInteger, ForeignKey('discorduser.id', ondelete="CASCADE"), nullable=True)
    discord_user = relationship('DiscordUser', lazy='noload')

    # User Information
    api_key = Column(String(), nullable=False)
    api_secret = Column(StringEncryptedType(String(), _key.encode('utf-8'), FernetEngine), nullable=False)
    exchange = Column(String, nullable=False)
    subaccount = Column(String, nullable=True)
    extra_kwargs = Column(PickleType, nullable=True)
    currency = Column(String(10), nullable=True)

    # Data
    name = Column(String, nullable=True)
    rekt_on = Column(DateTime(timezone=True), nullable=True)

    trades: AppenderQuery = relationship('Trade', lazy='noload',
                                         cascade="all, delete",
                                         back_populates='client')

    open_trades = relationship('Trade', lazy='noload',
                               back_populates='client',
                               primaryjoin="and_(Trade.client_id == Client.id, Trade.open_qty > 0)",
                               viewonly=True)

    history: AppenderQuery = relationship('Balance',
                                          back_populates='client',
                                          cascade="all, delete",
                                          lazy='dynamic',
                                          order_by='Balance.time',
                                          foreign_keys='Balance.client_id')

    #journals = relationship('Journal',
    #                        back_populates='client',
    #                        cascade="all, delete",
    #                        lazy='noload')

    transfers = relationship('Transfer', back_populates='client',
                             cascade='all, delete', lazy='noload')

    archived = Column(Boolean, default=False)
    invalid = Column(Boolean, default=False)

    currently_realized_id = Column(Integer, ForeignKey('balance.id', ondelete='SET NULL'), nullable=True)
    currently_realized = relationship('Balance',
                                      lazy='noload',
                                      foreign_keys=currently_realized_id,
                                      cascade="all, delete")

    last_transfer_sync = Column(DateTime(timezone=True), nullable=True)
    last_execution_sync = Column(DateTime(timezone=True), nullable=True)

    async def get_latest_balance(self, redis: Redis, currency=None):
        raw = await redis.hget(utils.join_args(NameSpace.CLIENT, self.id), key=NameSpace.BALANCE.value)
        if raw:
            as_json = customjson.loads(raw)
            return db_balance.Balance(
                realized=Decimal(as_json['realized']),
                unrealized=Decimal(as_json['unrealized']),
                total_transfered=Decimal(as_json['total_transfered'])
            )

    async def evaluate_balance(self, redis: Redis):
        if not self.currently_realized:
            return
        realized = getattr(self.currently_realized, 'realized', Decimal(0))
        unrealized = Decimal(0)
        for trade in self.open_trades:
            if trade.current_pnl:
                unrealized += trade.current_pnl.amount
            else:
                price = await redis.get(
                    utils.join_args(NameSpace.TICKER, self.exchange, trade.symbol)
                )
                if price:
                    unrealized += trade.calc_upnl(Decimal(str(price)))
        new = db_balance.Balance(
            realized=realized,
            unrealized=realized + unrealized,
            total_transfered=getattr(self.currently_realized, 'total_transfered', Decimal(0)),
            time=datetime.now(pytz.utc),
            client_id=self.id
        )
        # await redis.set(
        #    utils.join_args(NameSpace.CLIENT, NameSpace.BALANCE, self.id),
        #    new.serialize(data=True)
        # )
        return new

    async def update_journals(self, current_balance: db_balance.Balance, today: date, db_session: AsyncSession):
        today = today or date.today()

        for journal in self.journals:
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

    async def init_journal(self, new_journal: Journal, db_session: AsyncSession):
        new_journal.client = self
        intervals = await utils.calc_intervals(
            self,
            timedelta(days=1)
        )
        db_session.add_all([
            Chapter(
                start_date=interval.day,
                end_date=interval.day + new_journal.chapter_interval,
                client=self,
                journal=new_journal,
                start_balance=interval.start_balance,
                end_balance=interval.end_balance,
            )
            for interval in intervals
        ])
        db_session.add(new_journal)
        await db_session.commit()

    async def full_history(self):
        return await db_all(self.history.statement)

    async def latest(self):
        try:
            return await db_first(
                self.history.statement.order_by(None).order_by(desc(db_balance.Balance.time))
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

    async def get_balance_at_time(self, time: datetime, currency: str = None):
        amount_cls = db_balance.Balance
        stmt = self.history.statement.filter(
                amount_cls.time > time
            ).order_by(asc(amount_cls.time))

        balance = await db_first(stmt)

        if self.is_premium:
            # Probably the most beautiful query I've ever written
            subq = select(
                PnlData.id.label('pnl_id'),
                func.row_number().over(
                    order_by=asc(PnlData.time), partition_by=Trade.symbol
                ).label('row_number')
            ).join(
                PnlData.trade
            ).join(
                Execution, and_(
                    Execution.id == Trade.initial_execution_id,
                    Execution.time <= balance.time
                )
            ).filter(
                PnlData.time > balance.time,
                Trade.client_id == self.id
            ).subquery()

            full_stmt = select(
                subq,
                PnlData
            ).filter(
                PnlData.id == subq.c.pnl_id,
                subq.c.row_number <= 1
            )

            pnl_data = await db_all(full_stmt)

            return db_balance.Balance(
                realized=balance.realized,
                unrealized=balance.realized + sum(pnl.amount for pnl in pnl_data),
                time=balance.time
            )

        else:
            return balance

        # balance = await db_first(stmt)

        # if currency:
        #    return db_match_balance_currency(balance, currency)
        return balance

    @hybrid_property
    def is_active(self):
        return not all(not event.is_active for event in self.events)

    @hybrid_property
    def is_premium(self):
        return bool(
            True or self.user_id or getattr(self.discord_user, 'user', None)
        )

    async def initial(self):
        try:
            if self.id:
                return await db_first(self.history.statement.order_by(asc(db_balance.Balance.time)))
        except ValueError:
            raise
            # return balance.Balance(amount=config.REGISTRATION_MINIMUM, currency='$', error=None, extra_kwargs={})

    async def get_events_and_guilds_string(self, guilds: Optional[List[Guild]] = None):
        return ', '.join([await self.get_guilds_string(guilds), self.get_event_string()])

    def get_event_string(self):
        return ', '.join(
            event.name for event in self.events if event.is_active or event.is_free_for_registration()
        )

    async def get_guilds_string(self, guilds: Optional[List[Guild]] = None):
        if guilds is None:
            guilds = []

        associations = await db_select_all(GuildAssociation,
                                           client_id=self.id,
                                           discord_user_id=self.discord_user_id)

        if associations:
            guilds += await db_all(
                select(Guild).filter(
                    or_(*[Guild.id == association.guild_id for association in associations])
                )
            )

        return ', '.join(f'_{guild.name}_' for guild in guilds)

    async def get_discord_embed(self, guilds: Optional[List[Guild]] = None):

        embed = discord.Embed(title="User Information")
        utils.embed_add_value_safe(embed, 'Events', self.get_event_string())
        utils.embed_add_value_safe(embed, 'Servers', await self.get_guilds_string(guilds), inline=False)
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


# recent_history = select(
#    Client.id.label('id'),
#
#    Client.history.order_by(
#        desc(db_balance.Balance.time)
#    ).limit(3)
# ).alias()


def add_client_filters(stmt: Union[Select, Delete, Update], user: User, client_id: int = None) -> Union[Select, Delete, Update]:
    #user_checks = [Client.user_id == user.id]
    #if user.discord_user_id:
    #    user_checks.append(Client.discord_user_id == user.discord_user_id)
    return stmt.filter(
        Client.id == client_id if client_id else True,
        or_(
            Client.user_id == user.id,
            Client.discord_user_id == user.discord_user_id if user.discord_user_id else False
        )
    )
