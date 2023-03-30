from datetime import datetime
from typing import Dict, Optional, Any

import pydantic

from database.models import BaseModel
from database.dbmodels import Client
from database.dbmodels.client import ClientType
from database.dbmodels.user import User


class ClientApiInfo(BaseModel):
    api_key: str
    api_secret: str
    extra_kwargs: Optional[Dict]
    subaccount: Optional[str]
    sandbox: Optional[bool]

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


class ClientCreate(ClientApiInfo):
    name: Optional[str]
    exchange: str
    type: ClientType = ClientType.FULL

    def get(self, user: User = None) -> Client:
        client = Client(user=user, **self.dict(exclude={'import_since'}))
        if self.import_since:
            client.last_execution_sync = self.import_since
            client.last_transfer_sync = self.import_since
        return client
