from tradealpha.common.dbmodels.action import ActionType, Action
from tradealpha.common.models import OrmBaseModel, CreateableModel


class ActionCreate(CreateableModel):
    __table__ = Action

    namespace: str
    topic: str
    action_type: ActionType
    trigger_ids: dict
    extra: dict


class ActionInfo(OrmBaseModel, ActionCreate):
    id: int
