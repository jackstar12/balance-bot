from typing import List, Optional

from tradealpha.api.models import BaseModel, OutputID, InputID


class LabelInfo(BaseModel):
    id: OutputID
    name: str
    color: str

    class Config:
        orm_mode = True


class SetLabels(BaseModel):
    trade_id: InputID
    label_ids: list[InputID]


class RemoveLabel(BaseModel):
    trade_id: InputID
    label_id: InputID


class AddLabel(RemoveLabel):
    pass


class EditLabel(BaseModel):
    name: str
    color: str
