from database.models import BaseModel, OutputID, InputID
from database.models import OrmBaseModel


class CreateLabel(BaseModel):
    name: str
    color: str
    group_id: InputID


class LabelInfo(OrmBaseModel, CreateLabel):
    id: OutputID
    group_id: OutputID


class LabelGroupCreate(OrmBaseModel):
    name: str


class LabelGroupInfo(LabelGroupCreate):
    id: OutputID
    labels: list[LabelInfo]


class RemoveLabel(BaseModel):
    trade_id: InputID
    label_id: InputID


class AddLabel(RemoveLabel):
    pass
