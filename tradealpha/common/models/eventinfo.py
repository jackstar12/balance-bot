from datetime import datetime
from decimal import Decimal
from typing import Literal, TypedDict, Union, Optional
from uuid import UUID

from pydantic import Field, condecimal

from tradealpha.common.dbmodels import User, Event
from tradealpha.common.dbmodels.event import EventState, LocationModel
from tradealpha.common.models import OrmBaseModel, BaseModel, OutputID, CreateableModel
from tradealpha.common.models.document import DocumentModel
from tradealpha.common.models.gain import Gain


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


class _Common(BaseModel):
    registration_start: datetime
    registration_end: datetime
    start: datetime
    end: datetime
    name: str
    description: DocumentModel
    public: bool
    location: Union[DiscordLocation, WebLocation] = Field(..., disriminator='platform')
    max_registrations: int
    currency: Optional[str] = Field(default='USD')
    rekt_threshold: condecimal(gt=Decimal(-100), lt=Decimal(0)) = -99


class EventCreate(_Common, CreateableModel):

    def get(self, user: User):
        return Event(**self.__dict__, owner=user)

    # actions: Optional[list[ActionCreate]]


class EventInfo(_Common):
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
