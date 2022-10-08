import argparse
import asyncio
import logging
import os
import random
from typing import Dict

import discord
import discord.errors
import dotenv
from discord.ext import commands
from discord_slash import SlashCommand
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update, insert, literal, delete

from bot.cogs import *
from bot.config import *
from database.dbasync import async_session, db_all, redis, db_select
from database.dbmodels.client import Client
from database.dbmodels.discord.discorduser import DiscordUser
from database.dbmodels.discord.guild import Guild as GuildDB
from database.dbmodels.discord.guildassociation import GuildAssociation
from database.dbmodels.user import OAuthData
from database.enums import Tier
from common.messenger import Messenger
from database.models.discord.guild import UserRequest, GuildRequest, GuildData, MessageRequest
from database.redis.rpc import Server
from utils import setup_logger

dotenv.load_dotenv()
intents = discord.Intents().default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=PREFIX, self_bot=True, intents=intents)
slash = SlashCommand(bot)

redis_server = Server('discord', redis)


@redis_server.method(input_model=UserRequest)
def user_info(request: UserRequest):
    test = bot.get_user(request.user_id)

    return jsonable_encoder(
        OAuthData(
            avatar_url=str(test.avatar_url),
            account_name=test.name
        )
    )


@redis_server.method(input_model=UserRequest)
def guilds(request: UserRequest):
    return jsonable_encoder([
        GuildData(
            id=guild.id,
            name=guild.name,
            icon_url=str(guild.icon_url),
            text_channels=guild.text_channels,
            is_admin=guild.get_member(request.user_id).guild_permissions.administrator
        )
        for guild in bot.get_user(request.user_id).mutual_guilds
    ])


async def send_dm(self, user_id: int, message: str, embed: discord.Embed = None):
    user: discord.User = self.bot.get_user(user_id)
    if user:
        try:
            await user.send(content=message, embed=embed)
        except discord.Forbidden as e:
            logging.exception(f'Not allowed to send messages to {user}')


@redis_server.method(input_model=GuildRequest)
def guild(request: GuildRequest):
    g: discord.Guild = bot.get_guild(request.guild_id)
    m: discord.Member = g.get_member(request.user_id)
    return jsonable_encoder(
        GuildData(
            id=g.id,
            name=g.name,
            icon_url=str(g.icon_url),
            text_channels=[tc for tc in g.text_channels if tc.permissions_for(m).read_messages],
            is_admin=m.guild_permissions.administrator
        )
    )


def _get_channel(guild_id: int, channel_id: int) -> discord.TextChannel:
    guild = bot.get_guild(guild_id)
    if guild:
        return guild.get_channel(channel_id)


@redis_server.method(input_model=MessageRequest)
async def send(request: MessageRequest):
    channel = _get_channel(request.guild_id, request.channel_id)
    await channel.send(content=request.message,
                       embed=discord.Embed.from_dict(request.embed) if request.embed else None)
    return True


@bot.event
async def on_ready():
    if not os.path.exists(DATA_PATH):
        os.mkdir(DATA_PATH)

    for cog in cog_instances:
        await cog.on_ready()

    asyncio.create_task(
        redis_server.run()
    )

    db_guilds_by_id = {
        db_guild.id: db_guild for db_guild in await db_all(
            select(GuildDB), GuildDB.users, GuildDB.associations
        )
    }
    discord_users = await db_all(select(DiscordUser))
    # associations_by_guild_id = {guild.id: guild for guild in await db_all(select(GuildAssociation))}

    # Make sure database entries for guilds are up-to-date
    for guild in bot.guilds:
        db_guild = db_guilds_by_id.get(guild.id)
        if not db_guild:
            db_guild = GuildDB(id=guild.id, name=guild.name, tier=Tier.BASE, avatar=guild.banner)
            async_session.add(db_guild)
        if db_guild.name != guild.name:
            db_guild.name = guild.name
        for discord_user in discord_users:
            if guild.get_member(discord_user.id) and discord_user not in db_guild.users:
                async_session.add(
                    GuildAssociation(
                        guild_id=guild.id,
                        discord_user_id=discord_user.id,
                        client_id=None
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
        await async_session.execute(
            update(GuildDB).values(name=after.name)
        )
        await async_session.commit()


@bot.event
async def on_guild_join(guild: discord.Guild):
    db_guild = GuildDB(
        id=guild.id,
        tier=Tier.BASE,
        name=guild.name
    )

    async_session.add(db_guild)

    await async_session.execute(
        insert(GuildAssociation).from_select(
            [GuildAssociation.guild_id, GuildAssociation.discord_user_id],
            select(
                literal(guild.id),
                DiscordUser.id
            ).where(
                DiscordUser.id.in_(member.channel_id for member in guild.members)
            )
        )
    )

    await async_session.commit()


@bot.event
async def on_guild_leave(guild: discord.Guild):
    db_guild: GuildDB = await db_select(GuildDB, id=guild.id)

    await async_session.execute(
        delete(GuildAssociation).where(
            GuildAssociation.guild_id == guild.id
        )
    )

    test: discord.TextChannel
    if db_guild:
        for discord_user in db_guild.users:
            discord_user.guilds.remove(db_guild)
            if len(discord_user.guilds) == 0:
                # Delete?
                pass

    await async_session.commit()


@bot.event
async def on_member_join(member: discord.Member):
    await async_session.execute(
        insert(GuildAssociation).from_select(
            [GuildAssociation.guild_id, GuildAssociation.discord_user_id],
            select(
                literal(member.guild.id),
                DiscordUser.id
            ).where(
                DiscordUser.id == member._user
            )
        )
    )

    await async_session.commit()
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

messenger = Messenger(redis)

KEY = os.environ.get('BOT_KEY')
assert KEY, 'BOT_KEY missing'

cog_instances = [
    cog.setup(bot, redis, messenger, slash)
    for cog in [
        balance.BalanceCog,
        history.HistoryCog,
        events.EventsCog,
        misc.MiscCog,
        user.UserCog,
        alert.AlertCog,
        leaderboard.LeaderboardCog
    ]
]

if __name__ == '__main__':
    setup_logger()
    bot.run(KEY)
