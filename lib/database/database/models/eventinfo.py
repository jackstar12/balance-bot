from __future__ import annotations

import operator
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, TypedDict, Union, Optional, TYPE_CHECKING
from uuid import UUID

from pydantic import Field, condecimal

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
    rank: int
    gain: Gain
    time: datetime

    def __gt__(self, other):
        return self.gain.relative > other.gain.relative

    def __lt__(self, other):
        return self.gain.relative < other.gain.relative


class EventEntry(OrmBaseModel):
    user_id: UUID
    client_id: OutputID
    current: Optional[EventScore]
    rekt_on: Optional[datetime]
    init_balance: Optional[Balance]

    def __gt__(self, other):
        return safe_cmp(operator.gt, self.current, other.current) or safe_cmp(operator.gt, self.rekt_on, other.rekt_on)

    def __lt__(self, other):
        return safe_cmp(operator.lt, self.current, other.current) or safe_cmp(operator.lt, self.rekt_on, other.rekt_on)


class EventDetailed(EventInfo):
    pass
    # leaderboard: list[EventEntry]
    # registrations: list[ClientInfo]
    # leaderboard


class Stat(OrmBaseModel):
    best: UUID
    worst: UUID

    @classmethod
    def from_sorted(cls, sorted_clients: list[EventEntry]):
        return cls(
            best=sorted_clients[0].user_id,
            worst=sorted_clients[-1].user_id,
        )


class Summary(OrmBaseModel):
    gain: Stat
    stakes: Stat
    volatility: Stat
    avg_percent: Decimal
    total: Decimal


class Leaderboard(BaseModel):
    valid: list[EventEntry]
    unknown: list[EventEntry]
