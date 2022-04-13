from typing import List, Dict

from discord_slash import cog_ext, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_option

from balancebot.common import utils
from balancebot.api import dbutils
from balancebot.api.database import session
from balancebot.api.dbmodels.alert import Alert
from balancebot.bot.cogs.cogbase import CogBase
from balancebot.common.messenger import Category, SubCategory
from balancebot.common.models.selectionoption import SelectionOption


class AlertCog(CogBase):

    async def on_alert_trigger(self, data: Dict):
        user_id = data.get('discord_user_id')
        if user_id:
            message = f'Your alert for {data.get("symbol")}@{data.get("price")} just triggered!'
            note = data.get('note')
            if note:
                message += f'\nNote: _{note}_'
            await self.send_dm(
                user_id,
                message
            )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messenger.sub_channel(Category.ALERT, sub=SubCategory.FINISHED, callback=self.on_alert_trigger)

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
                option_type=SlashCommandOptionType.FLOAT
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
            exchange='ftx',
            discord_user_id=discord_user.id
        )

        session.add(alert)
        session.commit()

        await ctx.send('Alert created', embed=alert.get_discord_embed())

        self.messenger.pub_channel(Category.ALERT, SubCategory.NEW, obj=alert.serialize(data=True, full=False))

    @cog_ext.cog_subcommand(
        base="alert",
        name="delete",
        description="Delete an Alarm",
        options=[
            create_option(
                name="symbol",
                description="Symbol to delete",
                option_type=SlashCommandOptionType.STRING,
                required=True
            )
        ]
    )
    @utils.log_and_catch_errors()
    async def delete_alert(self, ctx: SlashContext):

        user = dbutils.get_user(ctx.author_id)
        query = session.query(Alert).filter(Alert.discord_user_id == user.id)
        alerts = query.all()

        def on_alert_select(selections: List[Alert]):
            for selection in selections:
                session.query(Alert).filter_by(id=selection.id).delete()
                self.messenger.pub_channel(Category.ALERT, SubCategory.DELETE, selection.id)
                session.commit()

        if len(alerts) > 1:
            component_row = utils.create_selection(
                slash=self.slash_cmd_handler,
                author_id=ctx.author_id,
                options=[
                    SelectionOption(
                        name=f'{alert.symbol}@{alert.price}',
                        value=str(alert.id),
                        description=alert.note,
                        object=alert
                    )
                    for alert in alerts
                ],
                callback=on_alert_select,
                max_values=1
            )
            await ctx.send(components=[component_row])
        else:
            query.delete()
            session.commit()

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

        embeds = [
            alert.get_discord_embed() for alert in user.alerts if alert.symbol == symbol or not symbol
        ]

        if len(embeds) > 0:
            await ctx.send(
                embeds=embeds
            )
        else:
            await ctx.send(f'You do not have any alerts active{f" for symbol {symbol}" if symbol else ""}')
