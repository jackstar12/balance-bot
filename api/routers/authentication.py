from fastapi import APIRouter, Depends, HTTPException
from fastapi_jwt_auth import AuthJWT
from api.dbmodels.balance import Balance
from api.dbmodels.user import User
import bcrypt

router = APIRouter(
    prefix="/",
    tags=["authentication"],
    dependencies=[],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


@router.post('/api/v1/register')
def register(email: str, password: str, Authorize: AuthJWT = Depends()):
    user = User.query.filter_by(email=email).first()
    if not user:
        salt = bcrypt.gensalt()
        new_user = User(
            email=email,
            salt=salt.decode('utf-8'),
            password=bcrypt.hashpw(password.encode(), salt).decode('utf-8')
        )
        Authorize.set_access_cookies(Authorize.create_access_token(subject=new_user.id), max_age=app.config['JWT_ACCESS_TOKEN_EXPIRES'].total_seconds())
        Authorize.set_refresh_cookies(Authorize.create_refresh_token(subject=new_user.id), max_age=app.config['JWT_ACCESS_TOKEN_EXPIRES'].total_seconds())
        return {'msg': 'Successfully registered'}
    else:
        raise HTTPException(status_code=400)


@router.post('/api/v1/login')
def login(email: str, password: str, Authorize: AuthJWT = Depends()):
    user = User.query.filter_by(email=email).first()
    if user:
        if bcrypt.hashpw(password.encode('utf-8'), user.salt.encode('utf-8')).decode('utf-8') == user.password:
            Authorize.set_access_cookies(Authorize.create_access_token(identity=user.id), max_age=app.config['JWT_ACCESS_TOKEN_EXPIRES'].total_seconds())
            Authorize.set_refresh_cookies(Authorize.create_refresh_token(identity=user.id), app.config['JWT_ACCESS_TOKEN_EXPIRES'].total_seconds())

            return {'msg': 'Successfully Logged in'}
    raise HTTPException(status_code=401)


@router.post('/api/v1/logout')
def logout(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    Authorize.unset_jwt_cookies()
    return {"msg": "logout successful"}
