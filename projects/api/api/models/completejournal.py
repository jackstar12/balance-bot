from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, NamedTuple, Set, Any

from api.routers.authgrant import AuthGrantInfo
from database.models import BaseModel, OutputID, InputID
from api.models.template import TemplateInfo, TemplateDetailed
from database.dbmodels.editing.journal import IntervalType, JournalType
from database.models.document import DocumentModel
from pydantic import NoneStr

MISSING = object()

class Gain(NamedTuple):
    relative: Decimal
    absolute: Decimal


class ChapterInfo(BaseModel):
    id: OutputID
    title: Optional[str]
    parent_id: Optional[OutputID]
    data: Optional[dict[str, Any]]
    created_at: datetime
    #balances: List[Balance]
    #performance: Optional[Gain]
    #start_balance: FullBalance
    #end_balance: FullBalance

    class Config:
        orm_mode = True


class JournalInfo(BaseModel):
    id: OutputID
    title: Optional[str]
    type: JournalType
    chapter_interval: Optional[IntervalType]
    created_at: datetime
    chapter_count: Optional[int]

    class Config:
        orm_mode = True


class JournalDetailedInfo(JournalInfo):
    client_ids: List[OutputID]
    overview: Optional[dict]
    default_template_id: Optional[OutputID]
    default_template: Optional[TemplateDetailed]
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
    grants: Optional[list[AuthGrantInfo]]
    template: Optional[TemplateInfo]


class ChapterUpdate(BaseModel):
    doc: Optional[DocumentModel]
    data: Optional[dict]
    parent_id: Optional[InputID]
    #trades: Optional[Set[str]]


class ChapterCreate(BaseModel):
    journal_id: InputID
    start_date: Optional[date]
    parent_id: Optional[InputID]
    template_id: Optional[InputID]
