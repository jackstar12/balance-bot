from __future__ import annotations
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING, Type
from uuid import UUID

import discord
from aioredis import Redis
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.hybrid import hybrid_property

from tradealpha.common.utils import join_args
from tradealpha.common.dbmodels.user import OAuthAccount
from tradealpha.common.dbasync import async_session, db_unique, db_select, db_select_all
import tradealpha.common.dbmodels.client as db_client
from tradealpha.common.dbmodels.mixins.serializer import Serializer

from sqlalchemy.orm import relationship, backref
from sqlalchemy import select, Column, String, BigInteger, ForeignKey

if TYPE_CHECKING:
    from tradealpha.common.dbmodels import Client, GuildAssociation


def get_display_name(dc_client: discord.Client, member_id: int, guild_id: int):
    try:
        return dc_client.get_guild(guild_id).get_member(member_id).display_name
    except AttributeError:
        return None


def get_client_display_name(dc: discord.Client, client: Client, guild_id: int):
    return get_display_name(dc, int(client.user.discord_user.account_id), int(guild_id))


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

        initial = await client.initial(async_session)
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
