from fastapi import Depends
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from balancebot.api.database_async import db_first
from balancebot.api.settings import settings
from balancebot.api.database import session
from fastapi import Depends
from fastapi_jwt_auth import AuthJWT
from balancebot.api.dbmodels.user import User


class CurrentUser:
    def __init__(self, clients=False, labels=False, alerts=False):
        self.options = []
        if clients:
            self.options.append(joinedload('clients'))
        if labels:
            self.options.append(joinedload('labels'))
        if alerts:
            self.options.append(joinedload('alerts'))

    async def __call__(self, Authorize: AuthJWT = Depends()):
        if not settings.testing:
            user = await db_first(
                select(User).filter_by(id=Authorize.get_jwt_subject()).options(*self.options)
            )
            # user = session.query(User).filter_by(id=Authorize.get_jwt_subject()).first()
        else:
            user = await db_first(
                select(User).options(*self.options)
            )
            # user = session.query(User).first()
        return user


async def current_user(clients=False, labels=False, alerts=False, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()

    options = []
    if clients:
        options.append(joinedload('clients'))
    if labels:
        options.append(joinedload('labels'))
    if alerts:
        options.append(joinedload('alerts'))

    if not settings.testing:
        user = await db_first(
            select(User).filter_by(id=Authorize.get_jwt_subject()).options(*options)
        )
        #user = session.query(User).filter_by(id=Authorize.get_jwt_subject()).first()
    else:
        user = await db_first(
            select(User).options(*options)
        )
        #user = session.query(User).first()
    return user
