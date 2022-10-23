from __future__ import annotations

from typing import List, TYPE_CHECKING, Optional

import discord
from aioredis import Redis
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, backref

import database.dbmodels.client as db_client
from database.dbasync import async_session, db_select
from database.dbmodels.user import OAuthAccount, OAuthData
from core.utils import join_args
from database.models.discord.guild import UserRequest
from database.redis import rpc

if TYPE_CHECKING:
    from database.dbmodels import Client, GuildAssociation


class DiscordUser(OAuthAccount):
    __serializer_forbidden__ = ['global_client', 'global_associations']

    global_associations: list[GuildAssociation] = relationship('GuildAssociation',
                                                               lazy='noload',
                                                               cascade="all, delete",
                                                               back_populates='discord_user')

    alerts = relationship('Alert',
                          backref=backref('discord_user', lazy='noload'),
                          lazy='noload',
                          cascade="all, delete")

    clients = relationship(
        'Client',
        secondary='guild_association',
        lazy='noload',
        cascade='all, delete'
    )

    __mapper_args__ = {
        "polymorphic_identity": "discord"
    }

    @hybrid_property
    def discord_id(self):
        return int(self.account_id)

    @discord_id.expression
    def discord_id(self):
        return self.account_id.cast(BigInteger)


    def get_display_name(self, dc: discord.Client, guild_id: int):
        try:
            return dc.get_guild(guild_id).get_member(self.discord_id).display_name
        except AttributeError:
            return None

    async def get_guild_client(self, guild_id, *eager, db: AsyncSession):
        association = self.get_guild_association(guild_id)

        if association:
            return await db_select(db_client.Client, eager=eager, session=db, id=association.client_id)

    def get_guild_association(self, guild_id=None, client_id=None):
        if not guild_id and not client_id:
            if len(self.global_associations) == 1:
                return self.global_associations[0]
        else:
            for association in self.global_associations:
                if association.guild_id == guild_id or (association.client_id == client_id and client_id):
                    return association

    async def get_client_embed(self, dc: discord.Client, client: Client):
        embed = discord.Embed(title="User Information")

        def embed_add_value_safe(name, value, **kwargs):
            if value:
                embed.add_field(name=name, value=value, **kwargs)

        embed_add_value_safe('Events', client.get_event_string())
        embed_add_value_safe('Servers', self.get_guilds_string(dc, client), inline=False)
        embed.add_field(name='Exchange', value=client.exchange)
        embed.add_field(name='Api Key', value=client.api_key)

        if client.subaccount:
            embed.add_field(name='Subaccount', value=client.subaccount)
        if client.extra_kwargs:
            for extra in client.extra_kwargs:
                embed.add_field(name=extra, value=client.extra_kwargs[extra])

        initial = await client.initial()
        if initial:
            embed.add_field(name='Initial Balance', value=initial.to_string())

        return embed

    @classmethod
    def get_embed(cls, fields: dict, **embed_kwargs):
        embed = discord.Embed(**embed_kwargs)
        for k, v in fields:
            embed.add_field(name=k, value=v)
        return embed

    async def get_discord_embed(self, dc: discord.Client) -> List[discord.Embed]:
        return [await self.get_client_embed(dc, client) for client in self.clients]

    def get_events_and_guilds_string(self, dc: discord.Client, client: Client):
        return join_args(
            self.get_guilds_string(dc, client.id),
            client.get_event_string(),
            denominator=', '
        )

    def get_guilds_string(self, dc: discord.Client, client_id: int):
        return ', '.join(
            f'_{dc.get_guild(association.guild_id).name}_'
            for association in self.global_associations if association.client_id == client_id
        )

    async def populate_oauth_data(self, redis: Redis) -> Optional[OAuthData]:
        client = rpc.Client('discord', redis)
        try:
            self.data = await client(
                'user_info', UserRequest(user_id=self.account_id)
            )
        except rpc.Error:
            pass

        return self.data
