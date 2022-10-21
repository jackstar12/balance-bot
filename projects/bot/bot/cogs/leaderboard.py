from datetime import datetime

from discord_slash import cog_ext, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_option
from sqlalchemy.ext.asyncio import AsyncSession

from bot import utils
from bot.cogs.cogbase import CogBase


class LeaderboardCog(CogBase):

    # @cog_ext.cog_subcommand(
    #     base="leaderboard",
    #     name="balance",
    #     description="Shows you the highest ranked users by $ balance",
    #     options=[]
    # )
    # @core.log_and_catch_errors()
    # @core.server_only
    # async def leaderboard_balance(self, ctx: SlashContext):
    #     await ctx.defer()
    #     await ctx.send(content='',
    #                    embed=await core.create_leaderboard(dc_client=self.bot,
    #                                                         guild_id=ctx.guild_id,
    #                                                         mode='balance'))

    @cog_ext.cog_subcommand(
        base="leaderboard",
        name="gain",
        description="Shows you the highest ranked users by % gain",
        options=[
            create_option(
                name="time",
                description="Timeframe for gain. If not specified, gain since start will be used.",
                required=False,
                option_type=SlashCommandOptionType.STRING
            )
        ]
    )
    @utils.log_and_catch_errors()
    @utils.time_args(('time', None))
    @utils.with_db
    @utils.server_only
    async def leaderboard_gain(self, ctx: SlashContext, db: AsyncSession, time: datetime = None):
        await ctx.defer()
        await ctx.send(
            embed=await utils.get_leaderboard(self.bot, ctx.guild_id, ctx.channel_id, since=time, db=db)
        )
