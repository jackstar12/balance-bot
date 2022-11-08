from datetime import date
from decimal import Decimal
from typing import List, Optional, NamedTuple, Set

from api.routers.authgrant import AuthGrantInfo
from database.models import BaseModel, OutputID, InputID
from api.models.template import TemplateInfo
from database.dbmodels.editing.journal import IntervalType, JournalType
from database.models.document import DocumentModel


class Gain(NamedTuple):
    relative: Decimal
    absolute: Decimal


class ChapterInfo(BaseModel):
    id: OutputID
    title: Optional[str]
    parent_id: Optional[OutputID]
    start_date: Optional[date]
    end_date: Optional[date]

    #balances: List[Balance]
    #performance: Optional[Gain]
    #start_balance: FullBalance
    #end_balance: FullBalance

    class Config:
        orm_mode = True


class JournalInfo(BaseModel):
    id: OutputID
    client_ids: List[OutputID]
    title: Optional[str]
    type: JournalType
    chapter_interval: Optional[IntervalType]

    class Config:
        orm_mode = True


class JournalDetailedInfo(JournalInfo):
    overview: Optional[dict]
    default_template_id: Optional[OutputID]
    default_template: Optional[TemplateInfo]
    chapters_info: list[ChapterInfo]
    grants: Optional[list[AuthGrantInfo]]


class JournalUpdate(BaseModel):
    client_ids: Optional[Set[InputID]]
    title: Optional[str]
    overview: Optional[DocumentModel]
    public: Optional[bool]
    default_template_id: Optional[InputID]


class JournalCreate(BaseModel):
    client_ids: List[InputID]
    title: str
    type: JournalType

    chapter_interval: Optional[IntervalType]
    auto_generate: Optional[bool]

    default_template_id: Optional[InputID]


class DetailedChapter(ChapterInfo):
    #trades: List[Trade]
    data: Optional[dict]
    doc: Optional[DocumentModel]


class ChapterUpdate(BaseModel):
    doc: Optional[DocumentModel]
    data: Optional[dict]
    #trades: Optional[Set[str]]


class ChapterCreate(BaseModel):
    journal_id: int
    start_date: Optional[date]
    parent_id: Optional[InputID]
    template_id: Optional[InputID]