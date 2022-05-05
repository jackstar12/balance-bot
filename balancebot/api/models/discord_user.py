from typing import List

from pydantic import BaseModel

from balancebot.api.models.guild import Guild


class DiscordUserInfo(BaseModel):
    id: int
    name: str
    avatar: str
    guilds: List[Guild]

    class Config:
        orm_mode = True