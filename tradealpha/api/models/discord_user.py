from typing import List, Optional

from tradealpha.api.models import BaseModel, OutputID

from tradealpha.api.models.guild import Guild, GuildAssociation


class DiscordUserInfo(BaseModel):
    id: OutputID
    name: str
    avatar: Optional[str]
    guilds: List[Guild]
    global_associations: List[GuildAssociation]

    class Config:
        orm_mode = True
