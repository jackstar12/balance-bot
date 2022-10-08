from datetime import datetime, date
from typing import Dict, Optional
from fastapi import Query
from pydantic import UUID4

from database.models.client import ClientCreate
from database.dbmodels.client import ClientType, ClientState
from database.models.balance import Balance
from database.models.interval import Interval
import database.dbmodels.mixins.querymixin as qmxin
from database.models import BaseModel, OutputID, InputID
from api.models.transfer import Transfer


def get_query_params(id: set[InputID] = Query(default=[]),
                     currency: str = Query(default='$'),
                     since: datetime = Query(default=None),
                     to: datetime = Query(default=None),
                     limit: int = Query(default=None)):
    return qmxin.QueryParams(
        client_ids=id,
        currency=currency,
        since=since,
        to=to,
        limit=limit
    )



class ClientCreateBody(ClientCreate):
    pass


class ClientCreateResponse(BaseModel):
    token: str
    balance: Balance


class ClientConfirm(BaseModel):
    token: str


class ClientEdit(BaseModel):
    name: Optional[str]
    state: Optional[ClientState]
    type: Optional[ClientType]


class ClientInfo(BaseModel):
    id: OutputID
    user_id: Optional[UUID4]
    discord_user_id: Optional[OutputID]

    api_key: str
    exchange: str
    subaccount: Optional[str]
    extra_kwargs: Optional[Dict]

    name: Optional[str]
    rekt_on: Optional[datetime]
    type: ClientType
    state: ClientState
    archived: bool
    invalid: bool

    created_at: datetime
    last_edited: Optional[datetime]

    class Config:
        orm_mode = True


class ClientOverview(BaseModel):
    initial_balance: Balance
    current_balance: Balance
    transfers: dict[str, Transfer]
    daily: dict[date, Interval]
