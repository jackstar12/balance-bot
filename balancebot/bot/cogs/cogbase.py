import logging
from typing import List

import discord
from aioredis import Redis
from discord import Embed
from discord.ext.commands import Bot
from discord.ext.commands.cog import Cog
from discord_slash import SlashCommand

from balancebot.bot.eventmanager import EventManager
from balancebot.common.messenger import Messenger


class CogBase(Cog):

    @classmethod
    def setup(cls, bot: Bot, redis: Redis, event_manager: EventManager, messenger: Messenger, slash_cmd_handler: SlashCommand):
        bot.add_cog(cls(bot, redis, event_manager, messenger, slash_cmd_handler))

    def __init__(self, bot: Bot, redis: Redis, event_manager: EventManager, messenger: Messenger, slash_cmd_handler: SlashCommand):
        self.bot = bot
        self.redis = redis
        self.event_manager = event_manager
        self.messenger = messenger
        self.slash_cmd_handler = slash_cmd_handler

    def on_ready(self):
        pass

    async def send_dm(self, user_id: int, message: str, embed: discord.Embed = None):
        user: discord.User = self.bot.get_user(user_id)
        if user:
            try:
                await user.send(content=message, embed=embed)
            except discord.Forbidden as e:
                logging.exception(f'Not allowed to send messages to {user}')
