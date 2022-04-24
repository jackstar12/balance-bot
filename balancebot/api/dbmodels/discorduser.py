from datetime import datetime
from typing import List, Callable
import discord
from discord_slash import SlashCommand
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot import api as client
from balancebot.api.database_async import async_session, db_unique, db_select
import  balancebot.api.dbmodels.client as db_client
from balancebot.api.dbmodels.guildassociation import GuildAssociation
from balancebot.api.dbmodels.serializer import Serializer

from balancebot.api.database import Base, session as session
from sqlalchemy.orm import relationship, backref
from sqlalchemy import select, Column, Integer, ForeignKey, String, BigInteger, Table

from balancebot.common.models.selectionoption import SelectionOption
import balancebot.common.utils as utils


class DiscordUser(Base, Serializer):
    __tablename__ = 'discorduser'
    __serializer_forbidden__ = ['global_client']

    id = Column(BigInteger(), primary_key=True)
    name = Column(String(), nullable=True)
    avatar = Column(String(), nullable=True)

    global_client_id = Column(Integer(), ForeignKey('client.id', ondelete="SET NULL"),  nullable=True)
    global_client = relationship('Client', lazy='noload', foreign_keys=global_client_id, post_update=True, uselist=False, cascade="all, delete")

    global_associations = relationship('GuildAssociation', lazy='raise', cascade="all, delete")

    alerts = relationship('Alert', backref=backref('discorduser', lazy='raise'), lazy='raise', cascade="all, delete")
    clients = relationship('Client', backref=backref('discorduser', lazy='raise'), lazy='raise', uselist=True, foreign_keys='[Client.discord_user_id]', cascade='all, delete')

    async def get_global_client(self, guild_id, *eager):
        association = self.get_global_association(guild_id)
        if association:
            return await db_unique(select(db_client.Client).filter_by(id=association.client_id), *eager)

    def get_global_association(self, guild_id = None, client_id = None):
        if not guild_id and not client_id:
            if len(self.global_associations) == 1:
                return self.global_associations[0]
        else:
            for association in self.global_associations:
                if association.guild_id == guild_id or association.client_id == client_id:
                    return association

    async def get_client_select(self, slash_cmd_handler: SlashCommand, callback: Callable):
        return utils.create_selection(
            slash_cmd_handler,
            self.id,
            options=[
                SelectionOption(
                    name=client.name if client.name else client.exchange,
                    value=str(client.id),
                    description=f'{f"{client.name}, " if client.name else ""}{client.exchange}, from {await client.get_events_and_guilds_string()}',
                    object=client
                )
                for client in self.clients
            ],
            callback=callback,
            max_values=1
        )

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
