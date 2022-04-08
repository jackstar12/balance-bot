import logging
import time

import discord
from discord_slash import cog_ext, SlashContext

from balancebot.common import utils
from balancebot.bot import config
from balancebot.bot.cogs.cogbase import CogBase
from balancebot.common.utils import de_emojify


class MiscCog(CogBase):

    @cog_ext.cog_slash(
        name="exchanges",
        description="Shows available exchanges"
    )
    async def exchanges(self, ctx):
        logging.info(f'New Interaction: Listing available exchanges for user {de_emojify(ctx.author.display_name)}')
        exchange_list = '\n'.join(config.EXCHANGES.keys())
        embed = discord.Embed(title="Available Exchanges", description=exchange_list)
        await ctx.send(embed=embed)

    @cog_ext.cog_slash(
        name="donate",
        description="Support dev?"
    )
    async def donate(self, ctx: SlashContext):
        embed = discord.Embed(
            description="**Do you like this bot?**\n"
                        "If so, maybe consider helping out a poor student :cry:\n\n"
                        "**BTC**: 1NQuRagfTziZ1k4ijc38cuCmCncWQFthSQ\n"
                        "**ZBD**: jackstar12@zbd.gg\n"
                        "**USDT (TRX)**: TPf47q7143stBkWicj4SidJ1DDeYSvtWBf\n"
                        "**USDT (BSC)**: 0x694cf86962f84d281d322887569b16935b48d9dd\n\n"
                        "@jacksn#9149."
        )
        await ctx.send(embed=embed)

    @cog_ext.cog_slash(
        name="ping",
        description="Ping"
    )
    @utils.log_and_catch_errors()
    async def ping(self, ctx: SlashContext):
        """Get the bot's current websocket and api latency."""
        start_time = time.time()
        message = discord.Embed(title="Testing Ping...")
        msg = await ctx.send(embed=message)
        end_time = time.time()
        message2 = discord.Embed(
            title=f":ping_pong:\nExternal: {round(self.bot.latency * 1000, ndigits=3)}ms\nInternal: {round((end_time - start_time), ndigits=3)}s")
        await msg.edit(embed=message2)

    @cog_ext.cog_slash(
        name="help",
        description="Help!"
    )
    async def help(self, ctx: SlashContext):
        embed = discord.Embed(
            title="**Usage**"
        )
        embed.add_field(
            name="How do I register?",
            value="https://github.com/jackstar12/balance-bot/blob/master/examples/register.md",
            inline=False
        )
        embed.add_field(
            name="Which information do I have to give the bot?",
            value="The bot only requires an **read only** api access",
            inline=False
        )
        # embed.add_field(
        #     name=""
        # )
        await ctx.send(embed=embed)


