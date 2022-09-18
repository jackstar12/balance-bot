from datetime import datetime
from typing import Dict, Optional, Any

import pydantic

from tradealpha.common.models import BaseModel
from tradealpha.common.dbmodels import Client
from tradealpha.common.dbmodels.client import ClientType
from tradealpha.common.dbmodels.user import User


class ClientCreate(BaseModel):
    name: Optional[str]
    exchange: str
    api_key: str
    api_secret: str
    type: ClientType = ClientType.FULL
    subaccount: Optional[str]
    sandbox: Optional[bool]
    extra_kwargs: Optional[Dict]
    import_since: Optional[datetime]

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

    def create(self, user: User = None) -> Client:
        client = Client(user=user, **self.dict(exclude={'import_since'}))
        if self.import_since:
            client.last_execution_sync = self.import_since
            client.last_transfer_sync = self.import_since
        return client
