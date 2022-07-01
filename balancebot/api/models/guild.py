from typing import List, Optional

from pydantic import BaseModel

from balancebot.api.models.event import Event
from balancebot.common.enums import Tier


class GuildAssociation(BaseModel):
    client_id: Optional[str]
    guild_id: str

    class Config:
        orm_mode = True


class Guild(BaseModel):
    id: str
    name: str
    tier: Tier
    avatar: Optional[str]
    events: List[Event]

    class Config:
        orm_mode = True
