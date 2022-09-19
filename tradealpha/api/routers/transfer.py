from fastapi import APIRouter, Depends, Body
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.api.dependencies import get_messenger, get_db
from tradealpha.api.users import CurrentUser
from tradealpha.api.models.transfer import Transfer
from tradealpha.api.utils.responses import OK, NotFound
from tradealpha.common.dbasync import db_exec, db_first
from tradealpha.common.dbmodels.client import Client, add_client_filters
from tradealpha.common.dbmodels.transfer import Transfer as TransferDB
from tradealpha.common.dbmodels.user import User

router = APIRouter(
    tags=["transfer"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


@router.get('/{transfer_id}')
async def update_transfer(transfer_id: int,
                          user: User = Depends(CurrentUser)):
    transfer = await db_first(
        add_client_filters(
            select(TransferDB).filter_by(
                id=transfer_id
            ).join(
                TransferDB.client
            ),
            user=user
        )
    )

    if transfer:
        return Transfer.from_orm(transfer)
    else:
        return NotFound('Invalid transfer_id')


@router.patch('/{transfer_id}')
async def update_transfer(transfer_id: int,
                          note: str = Body(...),
                          user: User = Depends(CurrentUser),
                          db_session: AsyncSession = Depends(get_db)):
    await db_exec(
        update(TransferDB).
        where(TransferDB.id == transfer_id).
        where(TransferDB.client_id == Client.id).
        where(Client.user_id == user.id).
        values(note=note),
        session=db_session
    )

    await db_session.commit()

    return OK('Updated')
