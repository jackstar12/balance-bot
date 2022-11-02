from datetime import datetime, date
from typing import Dict, Optional, TypedDict

from fastapi import Query
from pydantic import UUID4

import database.dbmodels.client as qmxin
from api.models.trade import Trade, BasicTrade
from api.models.template import TemplateInfo
from database.enums import IntervalType
from database.models.eventinfo import EventInfo
from database.models import BaseModel, OutputID, InputID
from api.models.transfer import Transfer
from database.dbmodels.client import ClientType, ClientState
from database.models.balance import Balance
from database.models.client import ClientCreate
from database.models.interval import Interval


def get_query_params(id: set[InputID] = Query(default=[]),
                     currency: str = Query(default='USD'),
                     since: datetime = Query(default=None),
                     to: datetime = Query(default=None),
                     limit: int = Query(default=None),
                     order: str = Query(default='asc')):
    return qmxin.ClientQueryParams(
        client_ids=id,
        currency=currency,
        since=since,
        to=to,
        limit=limit,
        order=order
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
    trade_template_id: Optional[InputID]


class ClientInfo(BaseModel):
    id: OutputID
    user_id: Optional[UUID4]
    discord_user_id: Optional[OutputID]

    exchange: str
    name: Optional[str]
    type: ClientType
    state: ClientState
    trade_template_id: Optional[OutputID]

    created_at: datetime
    last_edited: Optional[datetime]
    subaccount: Optional[str]
    api_key: str
    extra_kwargs: Optional[Dict]

    class Config:
        orm_mode = True


class Test(TypedDict):
    name: str


class ClientDetailed(ClientInfo):
    # More detailed information
    created_at: datetime
    last_edited: Optional[datetime]
    subaccount: Optional[str]
    api_key: str
    extra_kwargs: Optional[Dict]

    # Relations
    trade_template: Optional[TemplateInfo]
    events: Optional[list[EventInfo]]


class _Common(BaseModel):
    total: Interval
    transfers: list[Transfer]


class ClientOverviewCache(_Common):
    id: int
    daily_balance: list[Balance]


class ClientOverview(_Common):
    recent_trades: list[BasicTrade]
    intervals: dict[IntervalType, list[Interval]]
