from http import HTTPStatus

from fastapi import APIRouter, Depends, Body
from fastapi.exceptions import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.utils.client import get_user_client
from balancebot.common.dbasync import async_session, db_first, db_eager, db_all, db_select, db
from balancebot.api.dependencies import CurrentUser, get_db
from balancebot.common.dbsync import session

from balancebot.common.dbmodels.client import Client, add_client_filters
from balancebot.common.dbmodels.label import Label
from balancebot.common.dbmodels.trade import Trade, trade_association
from balancebot.common.dbmodels.user import User
from balancebot.api.models.label import SetLabels, RemoveLabel, AddLabel, PatchLabel, CreateLabel
from balancebot.api.utils.responses import BadRequest, OK, Response

router = APIRouter(
    prefix="/label",
    tags=["label"],
    dependencies=[Depends(CurrentUser)],
    responses={
        401: {"detail": "Wrong Email or Password"},
        400: {"detail": "Email is already used"}
    }
)


async def get_label(id: int, user: User):
    label: Label = await db_select(Label, id=id)
    if label:
        if label.user_id == user.id:
            return label
        else:
            return Response('You are not allowed to delete this label', code=40100, status=HTTPStatus.UNAUTHORIZED)
    else:
        BadRequest('Invalid ID')


@router.post('/')
async def create_label(body: CreateLabel, user: User = Depends(CurrentUser)):
    label = Label(name=body.name, color=body.color, user_id=user.id)
    async_session.add(label)
    await async_session.commit()
    return label.serialize()


@router.delete('/')
async def delete_label(id: int = Body(...), user: User = Depends(CurrentUser)):
    result = await get_label(id, user)
    if isinstance(result, Label):
        await async_session.delete(result)
        await async_session.commit()
        return {'msg': 'Success'}, HTTPStatus.OK
    else:
        return result


@router.patch('/')
async def update_label(body: PatchLabel, user: User = Depends(CurrentUser)):
    result = await get_label(body.id, user)
    if isinstance(result, Label):
        if body.name:
            result.name = body.name
        if body.color:
            result.color = body.color
        await async_session.commit()
        return OK('Success')
    else:
        return result


async def add_trade_filters(stmt, user: User, client_id: int, trade_id: int, label_id: int = None, db_session=None):
    client = await get_user_client(user, client_id, db=db_session)
    if client:
        return stmt.filter(
            Trade.id == trade_id,
            Trade.client_id == client_id
        )
    else:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail='Invalid Client ID'
        )


@router.post('/trade')
async def add_label(body: AddLabel, user: User = Depends(CurrentUser), db_session: AsyncSession = Depends(get_db)):
    trade = await db_first(
        db_eager(
            await add_trade_filters(select(Trade), user, body.trade_id, body.label_id),
            Trade.labels
        ),
        session=db_session
    )
    if trade:
        label = await db_first(select(Label).filter(
            Label.id == body.label_id,
            Label.client_id == body.client_id
        ))
        if label:
            if label not in trade.labels:
                trade.labels.append(label)
            else:
                return BadRequest('Trade already has this label')
        else:
            return BadRequest('Invalid Label ID')


@router.delete('/trade')
async def remove_label(body: RemoveLabel, user: User = Depends(CurrentUser)):
    trade = await db_first(
        db_eager(
            await add_trade_filters(select(Trade), user, body.client_id, body.trade_id, body.label_id),
            Trade.labels
        )
    )
    if isinstance(trade, Trade):
        label = session.query(Label).filter(
            Label.id == body.label_id,
            Label.client_id == body.client_id
        ).first()
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
async def set_labels(body: SetLabels, user: User = Depends(CurrentUser)):
    trade = await db_first(
        await add_trade_filters(select(Trade), user, body.client_id, body.trade_id)
    )
    if trade:

        if len(body.label_ids) > 0:
            #await db(
            #    update(trade_association).where(
            #        trade_association.trade_id == trade.id,
            #
            #    )
            #)
            trade.labels = await db_all(
                select(Label).filter(
                    or_(
                        Label.id == label_id for label_id in body.label_ids
                    ),
                    Label.user_id == user.id
                )
            )
        else:
            trade.labels = []
        await async_session.commit()

        return OK('Success')
    else:
        return trade
