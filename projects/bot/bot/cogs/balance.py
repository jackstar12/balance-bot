import logging

import discord
from datetime import datetime

from discord_slash import cog_ext, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_option

from common.dbasync import async_session
from common.dbmodels.client import Client
from common.dbmodels.discord.discorduser import DiscordUser
from bot import utils, config
from common import dbutils
from bot.cogs.cogbase import CogBase
from common.calc import calc_gains, calc_daily


class BalanceCog(CogBase):

    @cog_ext.cog_slash(
        name="balance",
        description="Gives balance of user",
        options=[
            create_option(
                name="user",
                description="User to get balance for",
                required=False,
                option_type=6
            ),
            create_option(
                name="currency",
                description="Currency to show. Not supported for all exchanges",
                required=False,
                option_type=3
            )
        ]
    )
    @utils.log_and_catch_errors()
    @utils.set_author_default(name='user')
    async def balance(self, ctx: SlashContext, user: discord.Member = None, currency: str = None):
        if currency is None:
            currency = 'USD'
        currency = currency.upper()

        if ctx.guild:
            registered_user = await dbutils.get_discord_client(user.id, ctx.guild.id)

            await ctx.defer()

            usr_balance = await registered_user.get_latest_balance(self.redis, async_session, currency)
            if not usr_balance:
                await ctx.send(f'There are no records about {user.display_name}\'s balance')
            if usr_balance.error is None:
                await ctx.send(f'{user.display_name}\'s balance: {usr_balance.to_string()}')
            else:
                await ctx.send(f'Error while getting {user.display_name}\'s balance: {usr_balance.error}')
        else:
            user: DiscordUser = await dbutils.get_discord_user(ctx.author_id, eager_loads=[
                (DiscordUser.clients, Client.events),
                DiscordUser.global_associations
            ])

            await ctx.defer()

            for user_client in user.clients:
                usr_balance = await user_client.get_latest_balance(self.redis, async_session, currency)
                balance_message = f'Your balance ({user.get_events_and_guilds_string(self.bot, user_client)}): '
                if not usr_balance:
                    await ctx.send('There are no records about your balance')
                if usr_balance.error is None:
                    await ctx.send(f'{balance_message}{usr_balance.to_string()}')
                else:
                    msg = user.get_events_and_guilds_string(self.bot, user_client)
                    await ctx.send(f'Error while getting your balance ({msg}): {usr_balance.error}')

    @cog_ext.cog_slash(
        name="gain",
        description="Calculate gain",
        options=[
            create_option(
                name="user",
                description="User to calculate gain for",
                required=False,
                option_type=6
            ),
            create_option(
                name="time",
                description="Time frame for gain. Default is start",
                required=False,
                option_type=3
            ),
            create_option(
                name="currency",
                description="Currency to calculate gain for",
                required=False,
                option_type=3
            )
        ]
    )
    @utils.log_and_catch_errors()
    @utils.time_args(('time', None))
    @utils.set_author_default(name='user')
    async def gain(self, ctx: SlashContext, user: discord.Member, time: datetime = None, currency: str = None):
        if currency is None:
            currency = 'USD'
        currency = currency.upper()

        if ctx.guild:
            registered_client = await dbutils.get_discord_client(
                user.id, ctx.guild_id, client_eager=[Client.events]
            )
            clients = [registered_client]
        else:
            discord_user = await dbutils.get_discord_user(
                ctx.author_id, eager_loads=[(DiscordUser.clients, Client.events, DiscordUser.global_associations)]
            )
            clients = discord_user.clients

        since_start = time is None
        time_str = utils.readable_time(time)

        await ctx.defer()

        user_gains = await calc_gains(
            clients,
            event=await dbutils.get_discord_event(ctx.guild_id, throw_exceptions=False),
            search=time,
            currency=currency,
            db=async_session
        )

        for client, gain in user_gains.items():
            guild = self.bot.get_guild(ctx.guild_id)
            if ctx.guild:
                gain_message = f'{user.display_name}\'s gain {"" if since_start else time_str}: '
            else:
                events_n_guild = discord_user.get_events_and_guilds_string(self.bot, client)
                gain_message = f"Your gain ({events_n_guild}): " if not guild else f"Your gain on {guild}: "
            if gain is None:
                logging.info(
                    f'Not enough data for calculating {utils.de_emojify(user.display_name)}\'s {time_str} gain on guild {guild}')
                if ctx.guild:
                    await ctx.send(f'Not enough data for calculating {user.display_name}\'s {time_str} gain')
                else:
                    s = discord_user.get_events_and_guilds_string(self.bot, client)
                    await ctx.send(f'Not enough data for calculating your gain ({s})')
            else:
                await ctx.send(
                    f'{gain_message}{round(gain.relative, ndigits=3)}% ({round(gain.absolute, ndigits=config.CURRENCY_PRECISION.get(currency, 3))}{currency})')

    @cog_ext.cog_slash(
        name="daily",
        description="Shows your daily gains.",
        options=[
            create_option(
                name="user",
                description="User to display daily gains for (Author default)",
                option_type=SlashCommandOptionType.USER,
                required=False
            ),
            create_option(
                name="amount",
                description="Amount of days",
                option_type=SlashCommandOptionType.INTEGER,
                required=False
            ),
            create_option(
                name="currency",
                description="Currency to use",
                option_type=SlashCommandOptionType.STRING,
                required=False
            )
        ]
    )
    @utils.log_and_catch_errors()
    @utils.set_author_default(name="user")
    async def daily(self, ctx: SlashContext, user: discord.Member, amount: int = None, currency: str = None):
        client = await dbutils.get_discord_client(user.id, ctx.guild_id, registration=True)
        await ctx.defer()
        daily_gains = await calc_daily(client, amount, ctx.guild_id, string=True, currency=currency)
        await ctx.send(embed=discord.Embed(
            title=f'Daily gains for {ctx.author.display_name}',
            description=f'```\n{daily_gains}```')
        )
