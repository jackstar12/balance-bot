from typing import Optional, List

from fastapi_users import models

from balancebot.api.models.alert import Alert
from balancebot.api.models.client import ClientInfo
from balancebot.api.models.discord_user import DiscordUserInfo
from balancebot.api.models.event import Event
from balancebot.api.models.label import Label


class User(models.BaseUser):
    discord_user_id: Optional[int]


class UserCreate(models.BaseUserCreate):
    discord_user_id: Optional[int]


class UserUpdate(models.BaseUserUpdate):
    discord_user_id: Optional[int]


class UserDB(User, models.BaseUserDB):
    discord_user_id: Optional[int]


class UserInfo(User):

    discord_user: Optional[DiscordUserInfo]
    all_clients: List[ClientInfo]
    labels: List[Label]
    alerts: List[Alert]

    class Config:
        orm_mode = True
