import logging

import discord
from aioredis import Redis
from discord.ext.commands import Bot
from discord.ext.commands.cog import Cog
from discord_slash import SlashCommand

from common.messenger import Messenger


class CogBase(Cog):

    @classmethod
    def setup(cls, bot: Bot, *args, **kwargs):
        instance = cls(bot, *args, **kwargs)
        bot.add_cog(instance)
        return instance

    def __init__(self, bot: Bot, redis: Redis, messenger: Messenger, slash_cmd_handler: SlashCommand):
        self.bot = bot
        self.redis = redis
        self.messenger = messenger
        self.slash_cmd_handler = slash_cmd_handler

    async def on_ready(self):
        pass

    async def send_dm(self, user_id: int, message: str, embed: discord.Embed = None):
        user: discord.User = self.bot.get_user(user_id)
        if user:
            try:
                await user.send(content=message, embed=embed)
            except discord.Forbidden as e:
                logging.exception(f'Not allowed to send messages to {user}')
