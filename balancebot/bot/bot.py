import argparse
import asyncio
import datetime as datetime
import logging
import os
import random
import sys
from datetime import datetime
from typing import Dict

import aiohttp
import discord
import discord.errors
from discord.ext import commands
from discord_slash import SlashCommand
from discord_slash.utils.manage_commands import create_choice

from balancebot.api.database import session
from balancebot.api.dbmodels.client import Client
from balancebot.bot.config import *
from balancebot.bot.cogs import *
from balancebot.bot.eventmanager import EventManager
from balancebot.collector.services.alertservice import AlertService
from balancebot.collector.usermanager import UserManager
from balancebot.common.messenger import Messenger, Category, SubCategory

intents = discord.Intents().default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=PREFIX, self_bot=True, intents=intents)
slash = SlashCommand(bot)


@bot.event
async def on_ready():
    user_manager.synch_workers()
    event_manager.initialize_events()
    asyncio.create_task(user_manager.start_fetching())

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
async def on_guild_join(guild: discord.Guild):
    commands = [slash.commands['register'], slash.commands['unregister'], slash.commands['clear']]

    for command in commands:
        for option in command.options:
            if option['name'] == 'guild':
                option['choices'].append(
                    create_choice(
                        name=guild.name,
                        value=guild.id
                    )
                )
    await slash.sync_all_commands(delete_from_unused_guilds=True)


async def on_rekt_async(data: Dict):
    client = session.query(Client).filter_by(id=data.get('id'))
    logging.info(f'Use {client.discorduser} is rekt')

    message = random.Random().choice(seq=REKT_MESSAGES)

    for guild_data in REKT_GUILDS:
        try:
            guild: discord.guild.Guild = bot.get_guild(guild_data['guild_id'])
            channel = guild.get_channel(guild_data['guild_channel'])
            member = guild.get_member(client.discorduser.user_id)
            if member:
                message_replaced = message.replace("{name}", member.display_name)
                embed = discord.Embed(description=message_replaced)
                await channel.send(embed=embed)
        except KeyError as e:
            logging.error(f'Invalid guild {guild_data=} {e}')
        except AttributeError as e:
            logging.error(f'Error while sending message to guild {e}')


user_manager = UserManager(exchanges=EXCHANGES,
                           fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                           data_path=DATA_PATH,
                           rekt_threshold=REKT_THRESHOLD)

parser = argparse.ArgumentParser(description="Run the bot.")
parser.add_argument("-r", "--reset", action="store_true", help="Archives the current data and resets it.")

args = parser.parse_known_args()

event_manager = EventManager(discord_client=bot)

messanger = Messenger()
messanger.sub_channel(Category.CLIENT, SubCategory.REKT, callback=on_rekt_async, pattern=True)

for cog in [
    balance.BalanceCog,
    history.HistoryCog,
    events.EventsCog,
    misc.MiscCog,
    register.RegisterCog,
    user.UserCog,
    alert.AlertCog
]:
    cog.setup(bot, user_manager, event_manager, messanger, slash)

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

    if http_session:
        pass
        # user_manager.session = http_session
    await bot.start(KEY)


if __name__ == '__main__':
    run()
