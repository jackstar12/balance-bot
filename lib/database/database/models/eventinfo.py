from datetime import datetime
from decimal import Decimal
from typing import Literal, TypedDict, Union, Optional
from uuid import UUID

from pydantic import validator, Field, condecimal

from database.models.gain import Gain
from database.dbmodels.event import EventState
from database.models.document import DocumentModel
from database.models import OrmBaseModel, BaseModel, OutputID


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
    rekt_treshhold: Optional[condecimal(lt=0)]
    currency: str


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
