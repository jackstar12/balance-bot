from http import HTTPStatus

from fastapi import APIRouter, Depends, Body
from fastapi.exceptions import HTTPException
from sqlalchemy import or_, select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.common.dbmodels import TradeDB
from tradealpha.api.utils.client import get_user_client
from tradealpha.common.dbasync import async_session, db_first, db_eager, db_all, db_select, db_exec, db_del_filter
from tradealpha.api.dependencies import get_db
from tradealpha.api.users import CurrentUser
from tradealpha.common.dbsync import session

from tradealpha.common.dbmodels.client import Client, add_client_filters
from tradealpha.common.dbmodels.label import Label as LabelDB
from tradealpha.api.models.labelinfo import LabelInfo
from tradealpha.common.dbmodels.trade import Trade, trade_association
from tradealpha.common.dbmodels.user import User
from tradealpha.api.models.labelinfo import SetLabels, RemoveLabel, AddLabel, EditLabel
from tradealpha.api.utils.responses import BadRequest, OK, Response, NotFound

router = APIRouter(
    prefix="/label",
    tags=["label"],
    dependencies=[Depends(CurrentUser)],
    responses={
        401: {"detail": "Wrong Email or Password"},
        400: {"detail": "Email is already used"}
    }
)


@router.post('/', response_model=LabelInfo)
async def create_label(body: EditLabel,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    label = LabelDB(name=body.name, color=body.color, user=user)
    db.add(label)
    await db.commit()
    return LabelInfo.from_orm(label)


@router.delete('/{label_id}/')
async def delete_label(label_id: int,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    result = await db_del_filter(LabelDB, id=label_id, user_id=user.id, session=db)
    await db.commit()
    if result.rowcount == 1:
        return OK('Deleted')
    else:
        return NotFound('Invalid label id')


@router.patch('/{label_id}/', response_model=LabelInfo)
async def update_label(label_id: int, body: EditLabel,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    label = await db_select(LabelDB, id=label_id, user_id=user.id, session=db)

    if label:
        label.name = body.name
        label.color = body.color

        await db.commit()

        return LabelInfo.from_orm(label)
    else:
        return NotFound('Invalid id')


def add_trade_filters(stmt, user: User, trade_id: int):
    return add_client_filters(
        stmt.filter(
            Trade.id == trade_id,
        ).join(Trade.client),
        user
    )


@router.post('/trade')
async def add_label(body: AddLabel,
                    user: User = Depends(CurrentUser),
                    db: AsyncSession = Depends(get_db)):
    verify_trade_id = await db_exec(
        add_trade_filters(
            select(TradeDB.id),
            user=user,
            trade_id=body.trade_id
        ),
        session=db
    )

    if not verify_trade_id:
        return BadRequest('Invalid Trade ID')

    verify_label_id = await db_select(
        LabelDB,
        id=body.label_id,
        user_id=user.id,
        session=db
    )

    if not verify_label_id:
        return BadRequest('Invalid Label ID')

    await db_exec(
        insert(trade_association).values(
            trade_id=body.trade_id,
            label_id=body.label_id
        ),
        session=db
    )
    await db.commit()

    return OK('Success')


@router.delete('/trade')
async def remove_label(body: RemoveLabel,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    trade = await db_first(
        add_trade_filters(select(Trade), user, body.trade_id),
        Trade.labels
    )
    label = await db_first(
        select(LabelDB).filter(
            LabelDB.id == body.label_id,
            LabelDB.client_id == body.client_id
        )
    )
    if label:
        if label in trade.labels:
            trade.labels.remove(label)
        else:
            return BadRequest('Trade already has this label')
    else:
        return NotFound('Invalid Label ID')


@router.patch('/trade')
async def set_labels(body: SetLabels,
                     user: User = Depends(CurrentUser),
                     db: AsyncSession = Depends(get_db)):
    trade = await db_first(
        add_trade_filters(select(Trade), user, body.trade_id),
        Trade.labels,
        session=db
    )

    if not trade:
        return BadRequest('Invalid Trade ID')

    if len(body.label_ids) > 0:
        trade.labels = await db_all(
            select(LabelDB).filter(
                LabelDB.id.in_(body.label_ids),
                LabelDB.user_id == user.id
            ),
            session=db
        )
    else:
        trade.labels = []
    await db.commit()
    return OK('Success')
