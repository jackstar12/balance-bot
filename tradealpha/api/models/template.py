from typing import Optional

from tradealpha.api.models import BaseModel, InputID, OutputID


class TemplateCreate(BaseModel):
    title: str
    journal_id: Optional[InputID]


class TemplateUpdate(BaseModel):
    title: Optional[str]
    doc: Optional[dict]
    public: Optional[bool]


class TemplateInfo(TemplateCreate):
    id: OutputID
    doc: Optional[dict]

    class Config:
        orm_mode = True
