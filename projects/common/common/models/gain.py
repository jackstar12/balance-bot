from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple, Optional, TYPE_CHECKING

from common import config
from common.models import BaseModel

if TYPE_CHECKING:
    from common.dbmodels.client import Client


class Gain(BaseModel):
    relative: Decimal
    absolute: Decimal

    def to_string(self, ccy: str):
        return f'{round(self.relative, ndigits=3)}% ({round(self.absolute, ndigits=config.CURRENCY_PRECISION.get(ccy, 3))}{ccy})'


class ClientGain(NamedTuple):
    client: Client
    relative: Optional[Decimal]
    absolute: Optional[Decimal]
