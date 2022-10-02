import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.api.authenticator import Authenticator
from tradealpha.api.dependencies import get_authenticator, get_db
from tradealpha.api.models.user import UserRead
from tradealpha.api.utils.responses import OK, CustomJSONResponse
from tradealpha.common.dbasync import db_select
from tradealpha.common.dbmodels.user import User

router = APIRouter(
    tags=["authentication"],
    dependencies=[],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


class AuthenticationBody(BaseModel):
    email: EmailStr
    password: str


#@router.post('/register')
#async def register(body: AuthenticationBody, authenticator: Authenticator = Depends(get_authenticator)):
#    user = await db_select(User, email=body.email)
#    if not user:
#        new_user = User(
#            email=body.email,
#            hashed_password=bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode('utf-8')
#        )
#
#        async_session.add(new_user)
#        await async_session.commit()
#        await async_session.refresh(new_user)
#
#        response = OK(msg='Successfully registered')
#        await authenticator.set_session_cookie(response, new_user)
#
#        return response
#    else:
#        raise HTTPException(status_code=400)


@router.post('/login')
async def login(body: AuthenticationBody,
                authenticator: Authenticator = Depends(get_authenticator),
                db: AsyncSession = Depends(get_db)):
    user = await db_select(User, email=body.email, session=db)
    if user:
        if bcrypt.checkpw(body.password.encode('utf-8'), user.hashed_password.encode('utf-8')):
            response = CustomJSONResponse(
                jsonable_encoder(UserRead.from_orm(user))
            )

            await authenticator.set_session_cookie(response, user)

            return response

    raise HTTPException(status_code=401, detail='Wrong email or password')


#@router.post('/refresh')
#def refresh(Authorize: AuthJWT = Depends()):
#    Authorize.jwt_refresh_token_required()
#
#    new_access_token = Authorize.create_access_token(subject=Authorize.get_jwt_subject(), fresh=False)
#    Authorize.set_access_cookies(new_access_token)
#
#    return OK("The token has been refreshed")


@router.post('/logout')
async def logout(request: Request, authenticator: Authenticator = Depends(get_authenticator)):
    await authenticator.invalidate_session(request)
    # Authorize.jwt_required()
    # Authorize.unset_jwt_cookies()
    return OK("Logout successfull")
