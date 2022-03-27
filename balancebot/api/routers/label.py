from http import HTTPStatus
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_

from balancebot.api.dependencies import current_user
from balancebot.api.database import session

from balancebot.api.dbmodels.client import Client, get_client_query
from balancebot.api.dbmodels.label import Label
from balancebot.api.dbmodels.trade import Trade
from balancebot.api.dbmodels.user import User

router = APIRouter(
    prefix="/label",
    tags=["label"],
    dependencies=[Depends(current_user)],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


def get_label(id: int, user: User):
    label: Label = session.query(Label).filter_by(id=id).first()
    if label:
        if label.user_id == user.id:
            return label
        else:
            return {'msg': 'You are not allowed to delete this Label'}, HTTPStatus.UNAUTHORIZED
    else:
        return {'msg': 'Invalid ID'}, HTTPStatus.BAD_REQUEST


class CreateLabel(BaseModel):
    name: str
    color: str


@router.post('/')
def create_label(body: CreateLabel, user: User = Depends(current_user)):
    label = Label(name=body.name, color=body.color, user_id=body.user.id)
    session.add(label)
    session.commit()
    return label.serialize(), HTTPStatus.OK


class DeleteLabel(BaseModel):
    id: int


@router.delete('/')
def delete_label(body: DeleteLabel, user: User = Depends(current_user)):
    result = get_label(body.id, user)
    if isinstance(result, Label):
        session.query(Label).filter_by(id=id).delete()
        session.commit()
        return {'msg': 'Success'}, HTTPStatus.OK
    else:
        return result


class PatchLabel(BaseModel):
    id: int
    name: str
    color: str


@router.patch('/')
def update_label(body: PatchLabel, user: User = Depends(current_user)):
    result = get_label(body.id, user)
    if isinstance(result, Label):
        if body.name:
            result.name = body.name
        if body.color:
            result.color = body.color
        session.commit()
        return {'msg': 'Success'}, HTTPStatus.OK
    else:
        return result


def get_trade_query(user: User, client_id: int, trade_id: int, label_id: int = None):
    client = get_client_query(user, client_id)
    if client:
        return session.query(Trade).filter(
            Trade.id == trade_id,
            Trade.client_id == client_id,
            Trade.label_id == label_id if label_id else True
        )
    else:
        return {'msg': 'Invalid Client ID'}, HTTPStatus.UNAUTHORIZED


class AddLabel(BaseModel):
    client_id: int
    trade_id: int
    label_id: int


@router.post('/trade')
def add_label(body: AddLabel, user: User = Depends(current_user)):
    trade = get_trade_query(user, body.trade_id, body.label_id).first()
    if isinstance(trade, Trade):
        label = session.query(Label).filter(
            Label.id == body.label_id,
            Label.client_id == body.client_id
        ).first()
        if label:
            if label not in trade.labels:
                trade.labels.append(label)
            else:
                return {'msg': 'Trade already has this label'}, HTTPStatus.BAD_REQUEST
        else:
            return {'msg': 'Invalid Label ID'}, HTTPStatus.BAD_REQUEST
    else:
        return trade


class RemoveLabel(BaseModel):
    client_id: int
    trade_id: int
    label_id: int


@router.delete('/trade')
def remove_label(body: RemoveLabel, user: User = Depends(current_user)):
    trade = get_trade_query(user, body.client_id, body.trade_id, body.label_id).first()
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


class SetLabels(BaseModel):
    client_id: int
    trade_id: int
    label_ids: List[int]


@router.patch('/trade')
def set_labels(body: SetLabels, user: User = Depends(current_user)):
    trade = get_trade_query(user, body.client_id, body.trade_id).first()
    if isinstance(trade, Trade):
        if len(body.label_ids) > 0:
            trade.labels = session.query(Label).filter(
                or_(
                    Label.id == label_id for label_id in body.label_ids
                ),
                Label.user_id == user.id
            ).all()
        else:
            trade.labels = []
        session.commit()
        return {'msg': 'Success'}, HTTPStatus.OK
    else:
        return trade
