from database.dbmodels.action import ActionType
from database.models import BaseModel, OrmBaseModel


class ActionCreate(BaseModel):
    namespace: str
    topic: str
    action_type: ActionType
    trigger_ids: dict
    extra: dict


class ActionInfo(OrmBaseModel, ActionCreate):
    id: int
