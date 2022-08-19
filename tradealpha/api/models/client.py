from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Set, Optional, Any
import pydantic
from fastapi import Query
from pydantic import UUID4
from starlette.requests import Request

from tradealpha.common.models.balance import Balance
from tradealpha.common.models.interval import Interval
from tradealpha.common.dbmodels.mixins.querymixin import QueryParams
from tradealpha.common.dbmodels.user import User
from tradealpha.common.dbmodels import Client
from tradealpha.api.models import BaseModel, OutputID, InputID
from tradealpha.api.models.transfer import Transfer
from tradealpha.common.models import OrmBaseModel


def get_query_params(id: set[InputID] = Query(default=[]),
                     currency: str = Query(default='$'),
                     since: datetime = Query(default=None),
                     to: datetime = Query(default=None),
                     limit: int = Query(default=None)):
    return QueryParams(
        client_ids=id,
        currency=currency,
        since=since,
        to=to,
        limit=limit
    )


class ClientCreate(BaseModel):
    name: Optional[str]
    exchange: str
    api_key: str
    api_secret: str
    subaccount: Optional[str]
    sandbox: Optional[bool]
    extra_kwargs: Optional[Dict]

    @pydantic.root_validator(pre=True)
    def build_extra(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        all_required_field_names = {
            field.alias for field in cls.__fields__.values() if field.alias != 'extra'
        }  # to support alias

        extra: Dict[str, Any] = {}
        for field_name in list(values):
            if field_name not in all_required_field_names:
                extra[field_name] = values.pop(field_name)
        values['extra'] = extra
        return values

    def create_client(self, user: User = None) -> Client:
        return Client(user=user, **self.dict())


class ClientCreateBody(ClientCreate):
    import_since: Optional[datetime]

    def create_client(self, user: User = None) -> Client:
        client = Client(user=user, **self.dict(exclude={'import_since'}))
        if self.import_since:
            client.last_execution_sync = self.import_since
            client.last_transfer_sync = self.import_since
        return client


class ClientCreateResponse(OrmBaseModel):
    token: str
    balance: Balance


class ClientConfirm(BaseModel):
    token: str


class ClientEdit(BaseModel):
    name: Optional[str]
    archived: Optional[bool]
    discord: Optional[bool]
    servers: Optional[Set[InputID]]
    events: Optional[Set[InputID]]


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

    archived: bool
    invalid: bool

    created_at: datetime
    last_edited: datetime

    class Config:
        orm_mode = True


class ClientOverview(BaseModel):
    initial_balance: Balance
    current_balance: Balance
    transfers: dict[str, Transfer]
    daily: dict[date, Interval]
