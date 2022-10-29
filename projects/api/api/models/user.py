import uuid
from datetime import datetime
from typing import Optional, List

from fastapi_users import schemas

from database.dbmodels.user import ProfileData, UserProfile
from database.models import BaseModel, OrmBaseModel
from database.models.document import DocumentModel


class OAuthInfo(schemas.BaseOAuthAccount):
    data: Optional[ProfileData]


class UserRead(schemas.BaseUser[uuid.UUID]):
    oauth_accounts: list[OAuthInfo]


class UserCreate(schemas.BaseUserCreate):
    pass


class UserPublicInfo(OrmBaseModel):
    id: uuid.UUID
    created_at: datetime
    profile: UserProfile
    about_me: Optional[DocumentModel]
