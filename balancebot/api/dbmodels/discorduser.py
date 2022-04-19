from datetime import datetime
from typing import List
import discord
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot import api as client
from balancebot.api.database_async import async_session, db_unique, db_select
from balancebot.api.dbmodels.client import Client
from balancebot.api.dbmodels.guildassociation import GuildAssociation
from balancebot.api.dbmodels.serializer import Serializer

from balancebot.api.database import Base, session as session
from sqlalchemy.orm import relationship
from sqlalchemy import select, Column, Integer, ForeignKey, String, BigInteger, Table


class DiscordUser(Base, Serializer):
    __tablename__ = 'discorduser'
    __serializer_forbidden__ = ['global_client']

    id = Column(BigInteger(), primary_key=True)
    name = Column(String(), nullable=True)
    user = relationship('User', backref='discorduser', lazy=True, uselist=False)
    avatar = Column(String(), nullable=True)

    global_client_id = Column(Integer(), ForeignKey('client.id', ondelete="SET NULL"),  nullable=True)
    global_client = relationship('Client', lazy='noload', foreign_keys=global_client_id, post_update=True, uselist=False, cascade="all, delete")

    global_clients = relationship('GuildAssociation', lazy='noload', cascade="all, delete")

    clients = relationship('Client', backref='discorduser', lazy='noload', uselist=True, foreign_keys='[Client.discord_user_id]', cascade='all, delete')
    alerts = relationship('Alert', backref='discorduser', lazy='noload', cascade="all, delete")

    async def get_global_client(self, guild_id, **eager):
        if not guild_id:
            if len(self.global_clients) == 1:
                association = self.global_clients[0]
            else:
                return
        else:
            association = await db_unique(
                select(GuildAssociation).filter_by(discorduser_id=self.id, guild_id=guild_id),
                **eager
            )
        if association:
            return await db_select(Client, id=association.client_id)

    @hybrid_property
    def user_id(self):
        return self.id

    async def get_discord_embed(self) -> List[discord.Embed]:
        return [await client.get_discord_embed() for client in self.clients]

    def get_display_name(self, dc_client: discord.Client, guild_id: int):
        try:
            return dc_client.get_guild(guild_id).get_member(self.user_id).display_name
        except AttributeError:
            return None


async def add_user_from_json(user_json) -> DiscordUser:
    exchange_name = user_json['exchange'].lower()
    if exchange_name == 'binance':
        exchange_name = 'binance-futures'

    rekt_on = user_json.get('rekt_on', None)
    if rekt_on:
        rekt_on = datetime.fromtimestamp(rekt_on)
    exchange: client.Client = client.Client(
        api_key=user_json['api_key'],
        api_secret=user_json['api_secret'],
        subaccount=user_json['subaccount'],
        extra_kwargs=user_json['extra'],
        rekt_on=rekt_on,
        exchange=exchange_name
    )
    session.add(exchange)
    user = DiscordUser(
        user_id=user_json['id'],
        clients=[exchange],
        global_client=exchange
    )

    session.add(user)
    await async_session.commit()
    return user
