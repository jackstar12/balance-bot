from __future__ import annotations

import operator
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, TypedDict, Union, Optional, TYPE_CHECKING
from uuid import UUID

from pydantic import Field, condecimal

from database.models.user import UserPublicInfo
from core import safe_cmp_default, safe_cmp
from database import dbmodels
from database.models import OrmBaseModel, BaseModel, OutputID, CreateableModel
from database.models.balance import Balance
from database.models.document import DocumentModel
from database.models.gain import Gain


if TYPE_CHECKING:
    from database.dbmodels import User


class LocationModel(OrmBaseModel):
    platform: str
    data: dict


class EventState(Enum):
    UPCOMING = "upcoming"
    ACTIVE = "active"
    REGISTRATION = "registration"
    ARCHIVED = "archived"


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
        return dbmodels.Event(**self.__dict__, owner=user)

    # actions: Optional[list[ActionCreate]]


class EventInfo(_Common):
    id: OutputID
    state: list[EventState]
    # name: str
    # public: bool

    class Config:
        orm_mode = True


class EventScore(OrmBaseModel):
    entry_id: OutputID
    rank: int
    gain: Gain
    time: datetime
    rekt_on: Optional[datetime]

    def __gt__(self, other):
        return self.gain.relative > other.gain.relative

    def __lt__(self, other):
        return self.gain.relative < other.gain.relative


class EventEntry(OrmBaseModel):
    id: OutputID
    user: UserPublicInfo
    nick_name: Optional[str]
    exchange: str
    init_balance: Optional[Balance]


class EventDetailed(EventInfo):
    owner: UserPublicInfo
    entries: list[EventEntry]
    pass
    # leaderboard: list[EventEntry]
    # registrations: list[ClientInfo]
    # leaderboard


class Stat(OrmBaseModel):
    best: OutputID
    worst: OutputID

    @classmethod
    def from_sorted(cls, sorted_clients: list[EventScore]):
        return cls(
            best=sorted_clients[0].entry_id,
            worst=sorted_clients[-1].entry_id,
        )


class Summary(OrmBaseModel):
    gain: Stat
    stakes: Stat
    volatility: Stat
    avg_percent: Decimal
    total: Decimal


class Leaderboard(BaseModel):
    valid: list[EventScore]
    unknown: list[OutputID]
