from fastapi import Depends
from fastapi_jwt_auth import AuthJWT
from balancebot.api.settings import settings
from balancebot.api.database import session
from fastapi import Depends
from fastapi_jwt_auth import AuthJWT
from balancebot.api.dbmodels.user import User


def current_user(Authorize: AuthJWT = Depends()):
    if not settings.testing:
        Authorize.jwt_required()
        user = session.query(User).filter_by(id=Authorize.get_jwt_subject()).first()
    else:
        user = session.query(User).first()
    return user
