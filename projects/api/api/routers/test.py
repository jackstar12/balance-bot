from fastapi import Depends, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import object_session

from api.dependencies import get_db
from database.dbmodels.user import User
from api.users import CurrentUser

router = APIRouter(
    tags=["transfer"],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


@router.get('/test')
async def test(user: User = Depends(CurrentUser), db: AsyncSession = Depends(get_db)):
    assert object_session(user) == db.sync_session
