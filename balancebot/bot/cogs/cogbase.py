from typing import List

import discord
from discord import Embed
from discord.ext.commands import Bot
from discord.ext.commands.cog import Cog
from discord_slash import SlashCommand

from balancebot.bot.eventmanager import EventManager
from balancebot.collector.usermanager import UserManager
from balancebot.common.messenger import Messenger


class CogBase(Cog):

    @classmethod
    def setup(cls, bot: Bot, user_manager: UserManager, event_manager: EventManager, messenger: Messenger, slash_cmd_handler: SlashCommand):
        bot.add_cog(cls(bot, user_manager, event_manager, messenger, slash_cmd_handler))

    def __init__(self, bot: Bot, user_manager: UserManager, event_manager: EventManager, messenger: Messenger, slash_cmd_handler: SlashCommand):
        self.bot = bot
        self.user_manager = user_manager
        self.event_manager = event_manager
        self.messenger = messenger
        self.slash_cmd_handler = slash_cmd_handler

    async def send_dm(self, user_id: int, message: str, embed: discord.Embed = None):
        user: discord.User = self.bot.get_user(user_id)
        if user:
            await user.send(content=message, embed=embed)
