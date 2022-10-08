from typing import List

from database.dbmodels.user import OAuthData
from database.models import OrmBaseModel
from database.models.discord.guild import Guild


class DiscordUserInfo(OrmBaseModel):
    data: OAuthData
    guilds: List[Guild]
