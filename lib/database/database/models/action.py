from typing import Literal, TypedDict, Union, Optional

from pydantic import HttpUrl, Field

from database.dbmodels.action import Action, ActionTrigger, ActionType
from database.models import OrmBaseModel, CreateableModel, OutputID
from database.models.platform import DiscordPlatform, PlatformModel


class WebhookData(TypedDict):
    url: HttpUrl


class WebhookPlatform(PlatformModel):
    name: Literal['webhook']
    data: WebhookData


class ActionCreate(CreateableModel):
    __table__ = Action

    name: Optional[str]
    type: ActionType
    topic: str
    platform: Union[DiscordPlatform, WebhookPlatform]
    trigger_type: ActionTrigger
    trigger_ids: Optional[dict]


class ActionInfo(OrmBaseModel, ActionCreate):
    id: OutputID


