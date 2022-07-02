import uuid
from typing import Optional, List

from fastapi_users import schemas

from tradealpha.api.models.alert import Alert
from tradealpha.api.models.client import ClientInfo
from tradealpha.api.models.discord_user import DiscordUserInfo
from tradealpha.api.models.event import Event
from tradealpha.api.models.label import Label


class UserRead(schemas.BaseUser[uuid.UUID]):
    discord_user_id: Optional[int]


class UserCreate(schemas.BaseUserCreate):
    discord_user_id: Optional[int]


class UserUpdate(schemas.BaseUserUpdate):
    discord_user_id: Optional[int]


class UserInfo(UserRead):

    discord_user: Optional[DiscordUserInfo]
    all_clients: List[ClientInfo]
    labels: List[Label]
    alerts: List[Alert]

    class Config:
        orm_mode = True
