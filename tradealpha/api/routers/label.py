from http import HTTPStatus

from fastapi import APIRouter, Depends, Body
from fastapi.exceptions import HTTPException
from sqlalchemy import or_, select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.common.dbmodels import TradeDB
from tradealpha.api.utils.client import get_user_client
from tradealpha.common.dbasync import async_session, db_first, db_eager, db_all, db_select, db, db_del_filter
from tradealpha.api.dependencies import CurrentUser, get_db
from tradealpha.common.dbsync import session

from tradealpha.common.dbmodels.client import Client, add_client_filters
from tradealpha.common.dbmodels.label import Label as LabelDB
from tradealpha.api.models.label import Label
from tradealpha.common.dbmodels.trade import Trade, trade_association
from tradealpha.common.dbmodels.user import User
from tradealpha.api.models.label import SetLabels, RemoveLabel, AddLabel, PatchLabel, CreateLabel
from tradealpha.api.utils.responses import BadRequest, OK, Response

router = APIRouter(
    prefix="/label",
    tags=["label"],
    dependencies=[Depends(CurrentUser)],
    responses={
        401: {"detail": "Wrong Email or Password"},
        400: {"detail": "Email is already used"}
    }
)


async def query_label(id: int, user: User):
    label: LabelDB = await db_select(LabelDB, id=id, user_id=user.id)
    if label:
        if label.user_id == user.id:
            return label
        else:
            raise HTTPException(detail='Unauthorized', code=40100, status=HTTPStatus.UNAUTHORIZED)
    else:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Unknown')


@router.post('/')
async def create_label(body: CreateLabel, user: User = Depends(CurrentUser)):
    label = LabelDB(name=body.name, color=body.color, user_id=user.id)
    async_session.add(label)
    await async_session.commit()
    return Label.construct(label.__dict__)


@router.delete('/')
async def delete_label(id: int = Body(...), user: User = Depends(CurrentUser)):
    await db_del_filter(LabelDB, id=id, user_id=user.id)
    await async_session.commit()
    return OK('Deleted')


@router.patch('/')
async def update_label(body: PatchLabel, user: User = Depends(CurrentUser)):
    values = {}
    if body.name:
        values['name'] = body.name
    if body.color:
        values['color'] = body.color
    await db(
        update(LabelDB).where(
            LabelDB.id == body.id,
            LabelDB.user_Id == user.id
        ).values(**values)
    )
    await async_session.commit()
    return OK('Success')


def add_trade_filters(stmt, user: User, client_id: int, trade_id: int):
    return add_client_filters(
        stmt.filter(
            Trade.id == trade_id,
            Trade.client_id == client_id,
        ).join(Trade.client),
        user, [client_id]
    )


@router.post('/trade')
async def add_label(body: AddLabel, user: User = Depends(CurrentUser), db_session: AsyncSession = Depends(get_db)):
    verify_trade_id = await db(
        add_trade_filters(
            select(TradeDB.id),
            user=user,
            client_id=body.client_id,
            trade_id=body.trade_id
        ),
        session=db_session
    )

    if not verify_trade_id:
        return BadRequest('Invalid Trade ID')

    verify_label_id = await db_select(
        LabelDB,
        id=body.label_id,
        user_id=user.id,
        session=db_session
    )

    if not verify_label_id:
        return BadRequest('Invalid Label ID')

    await db(
        insert(trade_association).values(
            trade_id=body.trade_id,
            label_id=body.label_id
        ),
        session=db_session
    )
    await db_session.commit()

    return OK('Success')


@router.delete('/trade')
async def remove_label(body: RemoveLabel, user: User = Depends(CurrentUser)):
    trade = await db_first(
        db_eager(
            await add_trade_filters(select(Trade), user, body.client_id, body.trade_id, body.label_id),
            Trade.labels
        )
    )
    if isinstance(trade, Trade):
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
                return {'msg': 'Trade already has this label'}, HTTPStatus.BAD_REQUEST
        else:
            return {'msg': 'Invalid Label ID'}, HTTPStatus.BAD_REQUEST
    else:
        return trade


@router.patch('/trade')
async def set_labels(body: SetLabels, user: User = Depends(CurrentUser), db_session: AsyncSession = Depends(get_db)):
    trade = await db_first(
        add_trade_filters(select(Trade), user, body.client_id, body.trade_id),
        Trade.labels
    )

    if not trade:
        return BadRequest('Invalid Trade ID')

    if trade:

        if len(body.label_ids) > 0:
            trade.labels = await db_all(
                select(LabelDB).filter(
                    LabelDB.id.in_(body.label_ids),
                    LabelDB.user_id == user.id
                )
            )
        else:
            trade.labels = []
        await async_session.commit()

        return OK('Success')
    else:
        return trade
