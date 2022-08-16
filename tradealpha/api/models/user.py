import uuid
from typing import Optional, List

from fastapi_users import schemas

from tradealpha.api.models import InputID
from tradealpha.api.models.alert import Alert
from tradealpha.api.models.client import ClientInfo
from tradealpha.api.models.discord_user import DiscordUserInfo
from tradealpha.api.models.event import Event
from tradealpha.api.models.labelinfo import LabelInfo


class UserRead(schemas.BaseUser[uuid.UUID]):
    discord_user_id: Optional[InputID]


class UserCreate(schemas.BaseUserCreate):
    discord_user_id: Optional[InputID]


class UserUpdate(schemas.BaseUserUpdate):
    discord_user_id: Optional[InputID]


class UserInfo(UserRead):

    discord_user: Optional[DiscordUserInfo]
    all_clients: List[ClientInfo]
    labels: List[LabelInfo]
    alerts: List[Alert]

    class Config:
        orm_mode = True
