from typing import Optional

from database.dbmodels.editing.template import TemplateType
from database.models import BaseModel, InputID, OutputID


class TemplateCreate(BaseModel):
    type: TemplateType
    journal_id: Optional[InputID]
    client_id: Optional[InputID]


class TemplateUpdate(BaseModel):
    doc: Optional[dict]
    public: Optional[bool]


class TemplateInfo(TemplateCreate):
    id: OutputID
    title: Optional[str]
    doc: Optional[dict]
    type: TemplateType

    class Config:
        orm_mode = True
