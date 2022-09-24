from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple, Optional, TYPE_CHECKING

from tradealpha.common.models import BaseModel

if TYPE_CHECKING:
    from tradealpha.common.dbmodels.client import Client


class Gain(BaseModel):
    relative: Decimal
    absolute: Decimal


class ClientGain(NamedTuple):
    client: Client
    relative: Optional[Decimal]
    absolute: Optional[Decimal]
