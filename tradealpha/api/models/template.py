from typing import Optional

from pydantic import BaseModel


class TemplateCreate(BaseModel):
    journal_id: int
    title: str


class TemplateUpdate(BaseModel):
    id: int
    title: Optional[str]
    content: Optional[dict]


class TemplateInfo(TemplateCreate):
    id: str
    content: dict

    class Config:
        orm_mode = True
