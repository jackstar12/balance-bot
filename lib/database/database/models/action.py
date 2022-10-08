from database.dbmodels.action import ActionType, Action
from database.models import OrmBaseModel, CreateableModel


class ActionCreate(CreateableModel):
    __table__ = Action

    namespace: str
    topic: str
    action_type: ActionType
    trigger_ids: dict
    extra: dict


class ActionInfo(OrmBaseModel, ActionCreate):
    id: int
