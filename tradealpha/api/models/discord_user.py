from typing import List

from tradealpha.common.dbmodels.user import OAuthData
from tradealpha.common.models import OrmBaseModel
from tradealpha.common.models.discord.guild import Guild


class DiscordUserInfo(OrmBaseModel):
    data: OAuthData
    guilds: List[Guild]
