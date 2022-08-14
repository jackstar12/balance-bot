from datetime import datetime

from tradealpha.api.models import BaseModel, OutputID


class Event(BaseModel):
    id: OutputID
    guild_id: OutputID
    channel_id: OutputID

    registration_start: datetime
    registration_end: datetime
    start: datetime
    end: datetime
    name: str
    description: str

    class Config:
        orm_mode = True
