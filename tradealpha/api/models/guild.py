from typing import List, Optional

from tradealpha.api.models import BaseModel, OutputID

from tradealpha.api.models.event import Event
from tradealpha.common.enums import Tier


class GuildAssociation(BaseModel):
    client_id: Optional[OutputID]
    guild_id: str

    class Config:
        orm_mode = True


class Guild(BaseModel):
    id: OutputID
    name: str
    tier: Tier
    avatar: Optional[str]
    events: List[Event]

    class Config:
        orm_mode = True
