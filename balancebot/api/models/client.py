from datetime import datetime
from typing import Dict, List, Set, Optional, Any

import pydantic
from pydantic import BaseModel, UUID4


class RegisterBody(BaseModel):
    name: str
    exchange: str
    api_key: str
    api_secret: str
    subaccount: str
    extra: Optional[Dict]

    @pydantic.root_validator(pre=True)
    def build_extra(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        all_required_field_names = {field.alias for field in cls.__fields__.values() if field.alias != 'extra'}  # to support alias

        extra: Dict[str, Any] = {}
        for field_name in list(values):
            if field_name not in all_required_field_names:
                extra[field_name] = values.pop(field_name)
        values['extra'] = extra
        return values


class ConfirmBody(BaseModel):
    token: str


class DeleteBody(BaseModel):
    id: int


class UpdateBody(BaseModel):
    id: int
    archived: Optional[bool]
    discord: Optional[bool]
    is_global: Optional[bool]
    servers: Optional[Set[int]]
    events: Optional[Set[int]]


class ClientInfo(BaseModel):
    id: int
    user_id: Optional[UUID4]
    discord_user_id: Optional[int]

    api_key: str
    exchange: str
    subaccount: Optional[str]
    extra_kwargs: Dict

    name: Optional[str]
    rekt_on: datetime

    archived: bool
    invalid: bool

    class Config:
        orm_mode = True
