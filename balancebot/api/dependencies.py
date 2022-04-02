from fastapi import Depends
from fastapi_jwt_auth import AuthJWT

from balancebot.api.database import session


def current_user(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    user = session.query(User).filter_by(id=Authorize.get_jwt_subject()).first()
    return user


from fastapi import Depends
from fastapi_jwt_auth import AuthJWT

from balancebot.api.dbmodels.user import User


def current_user(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    user = session.query(User).filter_by(id=Authorize.get_jwt_subject()).first()
    return user