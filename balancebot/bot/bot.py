import argparse
import asyncio
import datetime as datetime
import logging
import os
import random
import sys
from datetime import datetime
from sqlalchemy import select
from typing import Dict

import aiohttp
import discord
import discord.errors
from discord.ext import commands
from discord_slash import SlashCommand
from balancebot.common.database import session
from balancebot.common.database_async import async_session, db_all, redis
from balancebot.common.dbmodels.guildassociation import GuildAssociation
from balancebot.common.dbmodels.client import Client
from balancebot.common.dbmodels.discorduser import DiscordUser
from balancebot.common.dbmodels.guild import Guild
from balancebot.bot.config import *
from balancebot.bot.cogs import *
from balancebot.bot.eventmanager import EventManager
from balancebot.common.enums import Tier
from balancebot.common.messenger import Messenger, NameSpace, Category

intents = discord.Intents().default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=PREFIX, self_bot=True, intents=intents)
slash = SlashCommand(bot)


@bot.event
async def on_ready():
    event_manager.initialize_events()

    db_guilds_by_id = {
        db_guild.id: db_guild for db_guild in await db_all(
            select(Guild), Guild.users, Guild.global_clients
        )
    }
    discord_users = await db_all(select(DiscordUser))
    #associations_by_guild_id = {guild.id: guild for guild in await db_all(select(GuildAssociation))}

    # Make sure database entries for guilds are up-to-date
    for guild in bot.guilds:
        db_guild = db_guilds_by_id.get(guild.id)
        if not db_guild:
            db_guild = Guild(id=guild.id, name=guild.name, tier=Tier.BASE)
            async_session.add(db_guild)
        if db_guild.name != guild.name:
            db_guild.name = guild.name
        for discord_user in discord_users:
            if guild.get_member(discord_user.user_id) and discord_user not in db_guild.users:
                async_session.add(
                    GuildAssociation(
                        guild_id=guild.id,
                        discorduser_id=discord_user.id,
                        client_id=discord_user.global_client_id
                    )
                )

    await async_session.commit()

    logging.info('Bot Ready')
    print('Bot Ready')
    rate_limit = True
    while rate_limit:
        try:
            await slash.sync_all_commands(delete_from_unused_guilds=True)
            rate_limit = False
        except discord.errors.HTTPException as e:
            if e.status == 429:
                print('We are being rate limited. Retrying in 10 seconds...')
                await asyncio.sleep(10)
            else:
                raise e
    print('Done syncing')


@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild):
    if before.name != after.name:
        db_guild = session.query(Guild).filter_by(id=after.id).first()
        if db_guild:
            db_guild.name = after.name
            await async_session.commit()


@bot.event
async def on_guild_join(guild: discord.Guild):
    db_guild = Guild(
        id=guild.id,
        tier=Tier.BASE,
        name=guild.name
    )

    session.add(db_guild)

    discord_users = session.query(DiscordUser).all()
    for discord_user in discord_users:
        member = guild.get_member(discord_user.user_id)
        if member:
            discord_user.guilds.append(db_guild)

    await async_session.commit()

    # commands = [slash.commands['register'], slash.commands['unregister'], slash.commands['clear']]
    # for command in commands:
    #    for option in command.options:
    #        if option['name'] == 'guild':
    #            option['choices'].append(
    #                create_choice(
    #                    name=guild.name,
    #                    value=guild.id
    #                )
    #            )
    # await slash.sync_all_commands(delete_from_unused_guilds=True)


@bot.event
async def on_guild_leave(guild: discord.Guild):
    db_guild: Guild = session.query(Guild).filter_by(id=guild.id).first()

    if db_guild:
        for discord_user in db_guild.users:
            discord_user.guilds.remove(db_guild)
            if len(discord_user.guilds) == 0:
                # Delete?
                pass
    await async_session.commit()


@bot.event
async def on_member_join(member: discord.Member):
    pass


@bot.event
async def on_member_leave(member: discord.Member):
    pass


async def on_rekt_async(data: Dict):
    client = await async_session.get(Client, data.get('id'))
    logging.info(f'Use {client.discord_user} is rekt')

    message = random.Random().choice(seq=REKT_MESSAGES)

    for guild_data in REKT_GUILDS:
        try:
            guild: discord.guild.Guild = bot.get_guild(guild_data['guild_id'])
            channel = guild.get_channel(guild_data['guild_channel'])
            member = guild.get_member(client.discord_user_id)
            if member:
                message_replaced = message.replace("{name}", member.display_name)
                embed = discord.Embed(description=message_replaced)
                await channel.send(embed=embed)
        except KeyError as e:
            logging.error(f'Invalid guild {guild_data=} {e}')
        except AttributeError as e:
            logging.error(f'Error while sending message to guild {e}')


parser = argparse.ArgumentParser(description="Run the test_bot.")
parser.add_argument("-r", "--reset", action="store_true", help="Archives the current data and resets it.")

args = parser.parse_known_args()

event_manager = EventManager(discord_client=bot)

messenger = Messenger()

KEY = os.environ.get('BOT_KEY')
assert KEY, 'BOT_KEY missing'


async def run(http_session: aiohttp.ClientSession = None):
    def setup_logger(debug: bool = False):
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG if debug else logging.INFO)  # Change this to DEBUG if you want a lot more info
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        print(os.path.abspath(LOG_OUTPUT_DIR))
        if not os.path.exists(LOG_OUTPUT_DIR):
            os.mkdir(LOG_OUTPUT_DIR)
        from balancebot.api.settings import settings
        if settings.testing:
            log_stream = sys.stdout
        else:
            log_stream = open(LOG_OUTPUT_DIR + f'log_{datetime.now().strftime("%Y-%m-%d_%H_%M_%S")}.txt', "w")
        handler = logging.StreamHandler(log_stream)
        handler.setFormatter(formatter)

        logger.addHandler(handler)
        return logger

    setup_logger()
    messenger.sub_channel(NameSpace.CLIENT, Category.REKT, callback=on_rekt_async, channel_id=53)

    for cog in [
        balance.BalanceCog,
        history.HistoryCog,
        events.EventsCog,
        misc.MiscCog,
        register.RegisterCog,
        user.UserCog,
        alert.AlertCog
    ]:
        cog.setup(bot, redis, event_manager, messenger, slash)

    if http_session:
        pass
        # user_manager.session = http_session
    await bot.start(KEY)


if __name__ == '__main__':
    asyncio.run(run())
