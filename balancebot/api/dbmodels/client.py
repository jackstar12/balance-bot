from datetime import datetime
from typing import List, Optional, Union
import discord
import pytz
from aioredis import Redis
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType, BigInteger, or_, desc, asc, \
    Boolean, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, Query, backref

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm.dynamic import AppenderQuery
from sqlalchemy.sql import Select, Delete, Update
from sqlalchemy_utils.types.encrypted.encrypted_type import StringEncryptedType, FernetEngine

import os
import dotenv

from balancebot.api.database_async import db_first, db_all, async_session, db_select_all
from balancebot.api.dbmodels.balance import Balance
from balancebot.api.dbmodels.discorduser import DiscordUser
from balancebot.api.dbmodels.guild import Guild
from balancebot.api.dbmodels.guildassociation import GuildAssociation
from balancebot.api.dbmodels.serializer import Serializer
from balancebot.api.dbmodels.user import User
import balancebot.bot.config as config
from balancebot.api.database import Base, session
from balancebot.api.dbmodels import balance
import balancebot.common.utils as utils
# from balancebot.collector.usermanager import db_match_balance_currency
from balancebot.common.messenger import NameSpace

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
    discord_user_id = Column(BigInteger, ForeignKey('discorduser.id', ondelete="CASCADE"), nullable=True)

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
    trades: AppenderQuery = relationship('Trade', lazy='raise',
                                         cascade="all, delete", back_populates='client')
    open_trades = relationship('Trade', lazy='raise',
                               cascade="all, delete", back_populates='client',
                               primaryjoin="and_(Trade.client_id == Client.id, Trade.open_qty > 0.0)")
    history: AppenderQuery = relationship('Balance', backref=backref('client', lazy='noload'),
                                          cascade="all, delete", lazy='dynamic',
                                          order_by='Balance.time', foreign_keys='Balance.client_id')
    transfers = relationship('Transfer', backref=backref('client', lazy='noload'),
                             cascade='all, delete', lazy='noload')

    archived = Column(Boolean, default=False)
    invalid = Column(Boolean, default=False)

    currently_realized_id = Column(Integer, ForeignKey('balance.id', ondelete='SET NULL'), nullable=True)
    currently_realized = relationship('Balance', lazy='noload', foreign_keys=currently_realized_id,
                                      cascade="all, delete")

    last_transfer_sync = Column(DateTime(timezone=True), nullable=True)

    async def get_balance(self, redis: Redis, currency=None):
        return await redis.get(utils.join_args(NameSpace.CLIENT, NameSpace.BALANCE, self.id))

    async def evaluate_balance(self, redis: Redis):
        if not self.currently_realized:
            return
        amount = self.currently_realized.amount
        for trade in self.open_trades:
            if trade.upnl:
                amount += trade.upnl
            else:
                price = await redis.get(
                    utils.join_args(NameSpace.TICKER, trade.client.exchange, trade.symbol)
                )
                if price:
                    amount += trade.calc_upnl(float(price))
        new = Balance(
            amount=amount,
            time=datetime.now(pytz.utc)
        )
        #await redis.set(
        #    utils.join_args(NameSpace.CLIENT, NameSpace.BALANCE, self.id),
        #    new.serialize(data=True)
        #)
        return new

    async def full_history(self):
        return await db_all(self.history.statement)

    async def latest(self):
        try:
            return await db_first(
                self.history.statement.order_by(None).order_by(desc(Balance.time))
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

    async def get_balance_at_time(self, time: datetime, post: bool, currency: str = None):
        balance = await db_first(
            self.history.statement.filter(
                Balance.time > time if post else Balance.time < time
            ).order_by(asc(Balance.time) if post else desc(Balance.time))
        )

        # if currency:
        #    return db_match_balance_currency(balance, currency)
        return balance

    @hybrid_property
    def is_active(self):
        return not all(not event.is_active for event in self.events)

    @hybrid_property
    def is_premium(self):
        return bool(self.user_id or self.discord_user.user_id)

    async def initial(self):
        try:
            if self.id:
                return await db_first(self.history.statement.order_by(asc(Balance.time)))
        except ValueError:
            return balance.Balance(amount=config.REGISTRATION_MINIMUM, currency='$', error=None, extra_kwargs={})

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


def add_client_filters(stmt: Union[Select, Delete, Update], user: User, client_id: int) -> Union[
    Select, Delete, Update]:
    user_checks = [Client.user_id == user.id]
    if user.discord_user_id:
        user_checks.append(Client.discord_user_id == user.discord_user_id)
    return stmt.filter(
        Client.id == client_id,
        or_(*user_checks)
    )
