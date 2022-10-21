from datetime import datetime
from typing import Sequence, Literal

import discord
from discord_slash import cog_ext, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_option
from sqlalchemy import delete

from bot import config
from bot import utils
from bot.cogs.cogbase import CogBase
from database import utils as dbutils
from database.dbasync import db_exec, async_session, db_first
from database.dbmodels.balance import Balance
from database.dbmodels.client import Client
from database.dbmodels.discord.discorduser import DiscordUser


class HistoryCog(CogBase):

    @cog_ext.cog_subcommand(
        base="history",
        name="balance",
        description="Draws balance history of a user",
        options=[
            create_option(
                name="user",
                description="User to graph",
                required=False,
                option_type=SlashCommandOptionType.USER
            ),
            create_option(
                name="since",
                description="Start time for graph",
                required=False,
                option_type=SlashCommandOptionType.STRING
            ),
            create_option(
                name="to",
                description="End time for graph",
                required=False,
                option_type=SlashCommandOptionType.STRING
            ),
            create_option(
                name="currency",
                description="Currency to display history for (only available for some exchanges)",
                required=False,
                option_type=SlashCommandOptionType.STRING
            )
        ]
    )
    @utils.log_and_catch_errors()
    @utils.set_author_default(name='user')
    @utils.time_args(('since', None), ('to', None))
    async def balance_history(self, ctx, **kwargs):
        await self.history(ctx, **kwargs, mode='balance')

    @cog_ext.cog_subcommand(
        base="history",
        name="pnl",
        description="Your PNL History",
        options=[
            create_option(
                name="user",
                description="User to graph",
                required=False,
                option_type=SlashCommandOptionType.USER
            ),
            create_option(
                name="compare",
                description="Users to compare with",
                required=False,
                option_type=SlashCommandOptionType.STRING
            ),
            create_option(
                name="since",
                description="Start time for graph",
                required=False,
                option_type=SlashCommandOptionType.STRING
            ),
            create_option(
                name="to",
                description="End time for graph",
                required=False,
                option_type=SlashCommandOptionType.STRING
            ),
            create_option(
                name="currency",
                description="Currency to display history for (only available for some exchanges)",
                required=False,
                option_type=SlashCommandOptionType.STRING
            )
        ]
    )
    @utils.log_and_catch_errors()
    @utils.set_author_default(name='user')
    @utils.time_args(('since', None), ('to', None))
    async def pnl_history(self, ctx, **kwargs):
        await self.history(ctx, **kwargs, mode='pnl')

    async def history(self,
                      ctx: SlashContext,
                      user: discord.Member = None,
                      compare: str = None,
                      since: datetime = None,
                      to: datetime = None,
                      currency: str = None,
                      upnl=True,
                      mode: Literal['balance', 'pnl'] = 'balance'):
        if ctx.guild:
            registered_client = await dbutils.get_discord_client(user.id, ctx.guild.id)
            registrations = [(registered_client, user.display_name)]
        else:
            registered_user = await dbutils.get_discord_user(
                user.id, eager_loads=[
                    (DiscordUser.clients, Client.events),
                    DiscordUser.global_associations
                ]
            )
            registrations = [
                (client, registered_user.get_events_and_guilds_string(self.bot, client)) for client in registered_user.clients
            ]

        if compare:
            members_raw = compare.split(' ')
            if len(members_raw) > 0:
                for member_raw in members_raw:
                    if len(member_raw) > 3:
                        # ID Format: <@!373964325091672075>
                        #         or <@373964325091672075>
                        for pos in range(len(member_raw)):
                            if member_raw[pos].isnumeric():
                                member_raw = member_raw[pos:-1]
                                break
                        try:
                            member = ctx.guild.get_member(int(member_raw))
                        except ValueError:
                            # Could not cast to integer
                            continue
                        if member:
                            registered_client = await dbutils.get_discord_client(member.channel_id, ctx.guild.id)
                            registrations.append((registered_client, member.display_name))

        if currency is None:
            if len(registrations) > 1:
                currency = '%'
            else:
                currency = 'USD'
        currency = currency.upper()
        currency_raw = currency
        if '%' in currency:
            percentage = True
            currency = currency.rstrip('%')
            currency = currency.rstrip()
            if not currency:
                currency = 'USD'
        else:
            percentage = False

        await ctx.defer()

        await utils.create_history(
            to_graph=registrations,
            event=await dbutils.get_discord_event(ctx.guild_id, ctx.channel_id, throw_exceptions=False),
            start=since,
            end=to,
            currency_display=currency_raw,
            currency=currency,
            percentage=percentage,
            path=config.DATA_PATH + "tmp.png",
            mode=mode,
            include_upnl=upnl
        )

        file = discord.File(config.DATA_PATH + "tmp.png", "history.png")

        await ctx.send(content='', file=file)

    @classmethod
    async def clear_history(cls, clients: Sequence[Client], start: datetime, end: datetime):
        for client in clients:
            await db_exec(
                delete(Balance).filter(
                    Balance.client_id == client.id,
                    Balance.time >= start if start else True,
                    Balance.time <= end if end else True
                )
            )
        await async_session.commit()

    @cog_ext.cog_slash(
        name="clear",
        description="Clears your balance history",
        options=[
            create_option(
                name="since",
                description="Since when the history should be deleted",
                required=False,
                option_type=3
            ),
            create_option(
                name="to",
                description="Until when the history should be deleted",
                required=False,
                option_type=3,
            )
        ]
    )
    @utils.log_and_catch_errors()
    @utils.time_args(('since', None), ('to', None))
    async def clear(self, ctx: SlashContext, since: datetime = None, to: datetime = None):
        user = await dbutils.get_discord_user(ctx.author_id)

        ctx, clients = await utils.select_client(ctx, self.bot, self.slash_cmd_handler, user)

        from_to = ''
        if since:
            from_to += f' since **{since}**'
        if to:
            from_to += f' till **{to}**'

        ctx, consent = await utils.ask_for_consent(ctx, self.slash_cmd_handler,
                                                   msg_content=f'Do you really want to **delete** your history{from_to}?',
                                                   yes_message=f"Deleted your history{from_to}",
                                                   no_message="Clear cancelled",
                                                   hidden=True)

        if consent:
            await self.clear_history(
                clients,
                start=since,
                end=to
            )
