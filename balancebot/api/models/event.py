from datetime import datetime

from pydantic import BaseModel


class Event(BaseModel):
    id: int
    guild_id: int
    channel_id: int

    registration_start: datetime
    registration_end: datetime
    start: datetime
    end: datetime
    name: str
    description: str

    class Config:
        orm_mode = True
