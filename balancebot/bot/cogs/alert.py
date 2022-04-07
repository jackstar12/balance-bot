from discord_slash import cog_ext, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_option

from balancebot import utils
from balancebot.api import dbutils
from balancebot.api.dbmodels.alert import Alert
from balancebot.bot.cogs.cogbase import CogBase


class AlertCog(CogBase):

    @cog_ext.cog_subcommand(
        base="alert",
        name="new",
        description="Create New Alert",
        options=[
            create_option(
                name="symbol",
                description="Symbol to create Ticker for.",
                required=True,
                option_type=SlashCommandOptionType.STRING
            ),
            create_option(
                name="price",
                description="Price to trigger at.",
                required=True,
                option_type=SlashCommandOptionType.INTEGER
            ),
            create_option(
                name="note",
                description="Additional Note to pass when the alert triggers",
                required=False,
                option_type=SlashCommandOptionType.STRING
            )
        ]
    )
    @utils.log_and_catch_errors()
    async def new_alert(self, ctx: SlashContext, symbol: str, price: int, note: str = None):

        symbol = symbol.upper()

        discord_user = dbutils.get_user(ctx.author_id)

        alert = Alert(
            symbol=symbol,
            price=price,
            note=note,
            discord_user_id = discord_user.id
        )







    @cog_ext.cog_subcommand(
        base="alert",
        name="show",
        description="Show active Alerts",
        options=[
            create_option(
                name="symbol",
                description="Symbol to show alerts for",
                required=False,
                option_type=SlashCommandOptionType.STRING
            )
        ]
    )
    @utils.log_and_catch_errors()
    async def show_alerts(self, ctx: SlashContext, symbol: str = None):

        if symbol:
            symbol = symbol.upper()

        user = dbutils.get_user(ctx.author_id)





