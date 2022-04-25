from typing import List

from pydantic import BaseModel


class Label(BaseModel):
    id: int
    name: str
    color: str

    class Config:
        orm_mode = True


class PatchLabel(Label):
    class Config:
        orm_mode = False


class SetLabels(BaseModel):
    client_id: int
    trade_id: int
    label_ids: List[int]


class RemoveLabel(BaseModel):
    client_id: int
    trade_id: int
    label_id: int


class AddLabel(BaseModel):
    client_id: int
    trade_id: int
    label_id: int


class CreateLabel(BaseModel):
    name: str
    color: str
