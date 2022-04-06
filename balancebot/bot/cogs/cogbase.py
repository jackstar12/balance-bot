from discord.ext.commands import Bot
from discord.ext.commands.cog import Cog
from discord_slash import SlashCommand

from balancebot.bot.eventmanager import EventManager
from balancebot.usermanager import UserManager


class CogBase(Cog):

    @classmethod
    def setup(cls, bot: Bot, user_manager: UserManager, event_manager: EventManager, slash_cmd_handler: SlashCommand):
        bot.add_cog(cls(bot, user_manager, event_manager, slash_cmd_handler))

    def __init__(self, bot: Bot, user_manager: UserManager, event_manager: EventManager, slash_cmd_handler: SlashCommand):
        self.bot = bot
        self.user_manager = user_manager
        self.event_manager = event_manager
        self.slash_cmd_handler = slash_cmd_handler
