import uuid
from datetime import datetime
from typing import Optional, List

from fastapi_users import schemas

from database.models.user import ProfileData


class OAuthInfo(schemas.BaseOAuthAccount):
    data: Optional[ProfileData]


class UserRead(schemas.BaseUser[uuid.UUID]):
    oauth_accounts: list[OAuthInfo]


class UserCreate(schemas.BaseUserCreate):
    pass
