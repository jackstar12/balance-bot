import uuid
from typing import Optional, List

from fastapi_users import schemas

from tradealpha.api.models.alert import Alert
from tradealpha.api.models.client import ClientInfo
from tradealpha.api.models.labelinfo import LabelGroupInfo
from tradealpha.common.dbmodels.user import OAuthData


class OAuthInfo(schemas.BaseOAuthAccount):
    data: Optional[OAuthData]


class UserRead(schemas.BaseUser[uuid.UUID]):
    oauth_accounts: list[OAuthInfo]


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class UserInfo(UserRead):
    all_clients: List[ClientInfo]
    label_groups: List[LabelGroupInfo]
    alerts: List[Alert]

    class Config:
        orm_mode = True
