from typing import List

from pydantic import BaseModel

from balancebot.api.models.event import Event
from balancebot.common.enums import Tier


class Guild(BaseModel):
    id: int
    name: str
    tier: Tier
    avatar: str
    events: List[Event]

    class Config:
        orm_mode = True