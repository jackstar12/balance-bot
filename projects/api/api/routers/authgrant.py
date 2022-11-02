from datetime import datetime
from typing import Optional

from fastapi import Depends

from api.crudrouter import create_crud_router, Route
from api.dependencies import CurrentUser
from database.dbmodels import User
from database.dbsync import BaseMixin
from database.models import OrmBaseModel, OutputID, CreateableModel
from database.models.user import UserPublicInfo
from database.dbmodels.authgrant import AuthGrant


class AuthGrantInfo(OrmBaseModel):
    id: OutputID
    owner: UserPublicInfo
    expires: Optional[datetime]
    token: Optional[str]
    public: Optional[bool]
    data: Optional[dict]


class AuthGrantCreate(CreateableModel):
    expires: Optional[datetime]
    public: Optional[datetime]

    def get(self, user: User) -> BaseMixin:
        return AuthGrant(**self.dict(), user=user)


router = create_crud_router('/authgrant',
                            table=AuthGrant,
                            read_schema=AuthGrantInfo,
                            create_schema=AuthGrantCreate,
                            default_route=Route(
                                eager_loads=[AuthGrant.user]
                            ))


#@router.patch('/{grant_id}')
#async def update_grant(user: Depends(CurrentUser)):
#    pass
