from typing import List, Optional

from pydantic import BaseModel

from balancebot.api.models.guild import Guild, GuildAssociation


class DiscordUserInfo(BaseModel):
    id: str
    name: str
    avatar: Optional[str]
    guilds: List[Guild]
    global_associations: List[GuildAssociation]

    class Config:
        orm_mode = True
