from tradealpha.common.dbmodels.action import ActionType
from tradealpha.common.models import BaseModel, OrmBaseModel


class ActionCreate(BaseModel):
    namespace: str
    topic: str
    action_type: ActionType
    trigger_ids: dict
    extra: dict


class ActionInfo(OrmBaseModel, ActionCreate):
    id: int
