import logging

import discord
from datetime import datetime

from discord_slash import cog_ext, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_option

from balancebot.common import utils
from balancebot.api import dbutils
from balancebot.bot import config
from balancebot.bot.cogs.cogbase import CogBase
from balancebot.common.utils import de_emojify


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
            currency = '$'
        currency = currency.upper()

        if ctx.guild is not None:
            registered_user = dbutils.get_client(user.id, ctx.guild.id)

            await ctx.defer()

            usr_balance = await self.user_manager.get_client_balance(registered_user, currency)
            if usr_balance and usr_balance.error is None:
                await ctx.send(f'{user.display_name}\'s balance: {usr_balance.to_string()}')
            else:
                await ctx.send(f'Error while getting {user.display_name}\'s balance: {usr_balance.error}')
        else:
            user = dbutils.get_user(ctx.author_id)
            await ctx.defer()

            for user_client in user.clients:
                usr_balance = await self.user_manager.get_client_balance(user_client, currency)
                balance_message = f'Your balance ({user_client.get_event_string()}): '
                if usr_balance.error is None:
                    await ctx.send(f'{balance_message}{usr_balance.to_string()}')
                else:
                    await ctx.send(
                        f'Error while getting your balance ({user_client.get_event_string()}): {usr_balance.error}')

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
    @utils.time_args(names=[('time', None)])
    @utils.set_author_default(name='user')
    async def gain(self, ctx: SlashContext, user: discord.Member, time: datetime = None, currency: str = None):
        if currency is None:
            currency = '$'
        currency = currency.upper()

        if ctx.guild:
            registered_client = dbutils.get_client(user.id, ctx.guild_id)
            clients = [registered_client]
        else:
            user = dbutils.get_user(ctx.author_id)
            clients = user.clients

        since_start = time is None
        time_str = utils.readable_time(time)

        await ctx.defer()
        await self.user_manager.fetch_data(clients=clients)

        user_gains = utils.calc_gains(
            clients,
            event=dbutils.get_event(ctx.guild_id, throw_exceptions=False),
            search=time,
            currency=currency
        )

        for user_gain in user_gains:
            guild = self.bot.get_guild(ctx.guild_id)
            if ctx.guild:
                gain_message = f'{user.display_name}\'s gain {"" if since_start else time_str}: '
            else:
                gain_message = f"Your gain ({user_gain.client.get_event_string()}): " if not guild else f"Your gain on {guild}: "
            if user_gain.relative is None:
                logging.info(
                    f'Not enough data for calculating {de_emojify(user.display_name)}\'s {time_str} gain on guild {guild}')
                if ctx.guild:
                    await ctx.send(f'Not enough data for calculating {user.display_name}\'s {time_str} gain')
                else:
                    await ctx.send(f'Not enough data for calculating your gain ({user_gain.client.get_event_string()})')
            else:
                await ctx.send(
                    f'{gain_message}{round(user_gain.relative, ndigits=3)}% ({round(user_gain.absolute, ndigits=config.CURRENCY_PRECISION.get(currency, 3))}{currency})')

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
        client = dbutils.get_client(user.id, ctx.guild_id, registration=True)
        await ctx.defer()
        daily_gains = utils.calc_daily(client, amount, ctx.guild_id, string=True, currency=currency)
        await ctx.send(
            embed=discord.Embed(title=f'Daily gains for {ctx.author.display_name}',
                                description=f'```\n{daily_gains}```'))

