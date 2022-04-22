import discord
from datetime import datetime
from discord_slash import cog_ext, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_option

from balancebot.common import utils
from balancebot.api import dbutils
from balancebot.bot import config
from balancebot.bot.cogs.cogbase import CogBase
from balancebot.common.utils import create_yes_no_button_row


class HistoryCog(CogBase):

    @cog_ext.cog_slash(
        name="history",
        description="Draws balance history of a user",
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
    @utils.time_args(names=[('since', None), ('to', None)])
    async def history(self,
                      ctx: SlashContext,
                      user: discord.Member = None,
                      compare: str = None,
                      since: datetime = None,
                      to: datetime = None,
                      currency: str = None):
        if ctx.guild:
            registered_client = await dbutils.get_client(user.id, ctx.guild.id)
            registrations = [(registered_client, user.display_name)]
        else:
            registered_user = await dbutils.get_discord_user(user.id, clients=dict(events=True))
            registrations = [
                (client, await client.get_events_and_guilds_string()) for client in registered_user.clients
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
                            registered_client = await dbutils.get_client(member.id, ctx.guild.id)
                            registrations.append((registered_client, member.display_name))

        if currency is None:
            if len(registrations) > 1:
                currency = '%'
            else:
                currency = '$'
        currency = currency.upper()
        currency_raw = currency
        if '%' in currency:
            percentage = True
            currency = currency.rstrip('%')
            currency = currency.rstrip()
            if not currency:
                currency = '$'
        else:
            percentage = False

        await ctx.defer()

        await utils.create_history(
            to_graph=registrations,
            event=await dbutils.get_event(ctx.guild_id, ctx.channel_id, throw_exceptions=False),
            start=since,
            end=to,
            currency_display=currency_raw,
            currency=currency,
            percentage=percentage,
            path=config.DATA_PATH + "tmp.png"
        )

        file = discord.File(config.DATA_PATH + "tmp.png", "history.png")

        await ctx.send(content='', file=file)

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
    @utils.time_args(names=[('since', None), ('to', None)])
    async def clear(self, ctx: SlashContext, since: datetime = None, to: datetime = None):
        client = await dbutils.get_client(ctx.author_id, ctx.guild_id)

        from_to = ''
        if since:
            from_to += f' since **{since}**'
        if to:
            from_to += f' till **{to}**'

        async def clear_user(ctx):
            await self.user_manager.clear_client_data(client,
                                                      start=since,
                                                      end=to,
                                                      update_initial_balance=True)

        buttons = create_yes_no_button_row(
            self.slash_cmd_handler,
            author_id=ctx.author.id,
            yes_callback=clear_user,
            yes_message=f'Deleted your history{from_to}',
            no_message="Clear cancelled",
            hidden=True
        )

        await ctx.send(content=f'Do you really want to **delete** your history{from_to}?',
                       components=[buttons],
                       hidden=True)
