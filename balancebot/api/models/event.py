from datetime import datetime

from pydantic import BaseModel


class Event(BaseModel):
    id: str
    guild_id: str
    channel_id: str

    registration_start: datetime
    registration_end: datetime
    start: datetime
    end: datetime
    name: str
    description: str

    class Config:
        orm_mode = True
