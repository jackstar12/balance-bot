from fastapi import APIRouter, Depends, HTTPException
from fastapi_jwt_auth import AuthJWT
from starlette.responses import JSONResponse
from pydantic import BaseModel

from balancebot.api.database import session
from balancebot.api.dbmodels.user import User
import bcrypt

router = APIRouter(
    tags=["authentication"],
    dependencies=[],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


class AuthenticationBody(BaseModel):
    email: str
    password: str


@router.post('/register')
def register(body: AuthenticationBody, Authorize: AuthJWT = Depends()):
    user = session.query(User).filter_by(email=body.email).first()
    if not user:
        salt = bcrypt.gensalt()
        new_user = User(
            email=body.email,
            salt=salt.decode('utf-8'),
            password=bcrypt.hashpw(body.password.encode(), salt).decode('utf-8')
        )
        session.commit()
        session.refresh(new_user)
        Authorize.set_access_cookies(Authorize.create_access_token(subject=new_user.id))
        Authorize.set_refresh_cookies(Authorize.create_refresh_token(subject=new_user.id))
        return {'msg': 'Successfully registered'}
    else:
        raise HTTPException(status_code=400)


@router.post('/login')
def login(body: AuthenticationBody, Authorize: AuthJWT = Depends()):
    user = session.query(User).filter_by(email=body.email).first()
    if user:
        if bcrypt.hashpw(body.password.encode('utf-8'), user.salt.encode('utf-8')).decode('utf-8') == user.password:

            response = JSONResponse(
                {'msg': 'Successfully Logged in'}
            )

            Authorize.set_access_cookies(Authorize.create_access_token(subject=user.id), response=response)
            Authorize.set_refresh_cookies(Authorize.create_refresh_token(subject=user.id), response=response)

            return response

    raise HTTPException(status_code=401)


@router.post('/logout')
def logout(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    Authorize.unset_jwt_cookies()
    return {"msg": "logout successful"}
