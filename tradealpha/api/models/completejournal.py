from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import List, Literal, Optional, NamedTuple, Set

from pydantic import BaseModel

from tradealpha.api.models.amount import FullBalance
from tradealpha.common.dbmodels.balance import Balance
from tradealpha.common.models.gain import Gain
from tradealpha.api.models.trade import Trade


class BaseOrmModel(BaseModel):
    class Config:
        orm_mode = True


class JournalCreate(BaseModel):
    clients: List[int]
    title: str
    chapter_interval: timedelta
    auto_generate: bool


class JournalInfo(JournalCreate):
    id: int
    notes: Optional[str]

    class Config:
        orm_mode = True


class JournalUpdate(BaseOrmModel):
    clients: Optional[Set[int]]
    title: Optional[str]
    notes: Optional[str]
    auto_generate: Optional[bool]


class Gain(NamedTuple):
    relative: Decimal
    absolute: Decimal


class ChapterInfo(BaseModel):
    id: int
    start_date: date
    end_date: date
    balances: List[FullBalance]
    performance: Optional[Gain]
    #start_balance: FullBalance
    #end_balance: FullBalance

    class Config:
        orm_mode = True


class ChapterUpdate(BaseModel):
    notes: Optional[str]
    trades: Optional[Set[int]]


class ChapterCreate(BaseModel):
    start_date: date


class Chapter(ChapterInfo):
    #trades: List[Trade]
    notes: Optional[str]


class CompleteJournal(JournalInfo):
    chapters: List[ChapterInfo]
