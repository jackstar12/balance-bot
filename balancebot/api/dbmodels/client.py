from typing import List, Optional, Union
import discord
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

    # Data
    name = Column(String, nullable=True)
    rekt_on = Column(DateTime(timezone=True), nullable=True)
    trades: AppenderQuery = relationship('Trade', backref=backref('client', lazy='noload'), lazy='noload', cascade="all, delete")
    history: AppenderQuery = relationship('Balance', backref=backref('client', lazy='noload'),
                                          cascade="all, delete", lazy='dynamic',
                                          order_by='Balance.time', foreign_keys='Balance.client_id')

    archived = Column(Boolean, default=False)
    invalid = Column(Boolean, default=False)

    currently_realized_id = Column(Integer, ForeignKey('balance.id', ondelete='SET NULL'), nullable=True)
    currently_realized = relationship('Balance', lazy='joined', foreign_keys=currently_realized_id,
                                      cascade="all, delete")

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
                associations = await db_select_all(GuildAssociation, discorduser_id=self.discord_user_id, client_id=self.id, guild_id=guild_id)
            else:
                associations = await db_select_all(GuildAssociation, discorduser_id=self.discord_user_id, client_id=self.id)
            return bool(associations)
        elif self.user_id:
            return True

    @hybrid_property
    def is_active(self):
        return not all(not event.is_active for event in self.events)

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
                                           discorduser_id=self.discord_user_id)

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


def add_client_filters(stmt: Union[Select, Delete, Update], user: User, client_id: int) -> Union[Select, Delete, Update]:
    user_checks = [Client.user_id == user.id]
    if user.discord_user_id:
        user_checks.append(Client.discord_user_id == user.discorduser.id)
    return stmt.filter(
        Client.id == client_id,
        or_(*user_checks)
    )
