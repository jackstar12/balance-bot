from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Set, Optional, Any
import pydantic
from fastapi import Query
from pydantic import UUID4
from starlette.requests import Request

from tradealpha.common.models.client import ClientCreate
from tradealpha.common.dbmodels.client import ClientType, ClientState
from tradealpha.common.models.balance import Balance
from tradealpha.common.models.interval import Interval
import tradealpha.common.dbmodels.mixins.querymixin as qmxin
from tradealpha.api.models import BaseModel, OutputID, InputID
from tradealpha.api.models.transfer import Transfer


def get_query_params(id: set[InputID] = Query(default=[]),
                     currency: str = Query(default='USD'),
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
