from datetime import datetime
from decimal import Decimal
from typing import Literal, TypedDict, Union, Optional
from uuid import UUID

from pydantic import validator, Field

from tradealpha.common.models.gain import Gain
from tradealpha.common.dbmodels.event import EventState
from tradealpha.common.models.document import DocumentModel
from tradealpha.common.models import OrmBaseModel
from tradealpha.api.models import BaseModel, OutputID, InputID


class LocationModel(OrmBaseModel):
    platform: str
    data: dict


class DiscordData(TypedDict):
    guild_id: str
    channel_id: str


class DiscordLocation(LocationModel):
    platform: Literal['discord']
    data: DiscordData


class WebData(TypedDict):
    pass


class WebLocation(LocationModel):
    platform: Literal['web']
    data: WebData


class EventCreate(BaseModel):
    registration_start: datetime
    registration_end: datetime
    start: datetime
    end: datetime
    name: str
    description: DocumentModel
    public: bool
    location: Union[DiscordLocation, WebLocation] = Field(..., disriminator='platform')
    max_registrations: int


class EventInfo(EventCreate):
    id: OutputID
    state: list[EventState]

    class Config:
        orm_mode = True


class EventRank(OrmBaseModel):
    value: int
    time: Optional[datetime]


class EventScore(OrmBaseModel):
    user_id: UUID
    client_id: OutputID
    current_rank: EventRank
    gain: Gain
    rekt_on: Optional[datetime]


class EventDetailed(EventInfo):
    leaderboard: list[EventScore]
    # registrations: list[ClientInfo]
    # leaderboard
