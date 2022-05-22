import uuid
from typing import Optional, List

from fastapi_users import schemas

from balancebot.api.models.alert import Alert
from balancebot.api.models.client import ClientInfo
from balancebot.api.models.discord_user import DiscordUserInfo
from balancebot.api.models.event import Event
from balancebot.api.models.label import Label


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
