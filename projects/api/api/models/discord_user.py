from typing import List

from common.dbmodels.user import OAuthData
from common.models import OrmBaseModel
from common.models.discord.guild import Guild


class DiscordUserInfo(OrmBaseModel):
    data: OAuthData
    guilds: List[Guild]
