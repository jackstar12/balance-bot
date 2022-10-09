from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple, Optional, TYPE_CHECKING

from utils import round_ccy
from database.models import BaseModel

if TYPE_CHECKING:
    from database.dbmodels.client import Client


class Gain(BaseModel):
    relative: Optional[Decimal]
    absolute: Optional[Decimal]

    def to_string(self, ccy: str):
        if self.relative is not None and self.absolute is not None:
            return f'{round_ccy(self.relative, "%")}% ({round_ccy(self.absolute, ccy)}{ccy})'


class ClientGain(NamedTuple):
    client: Client
    relative: Optional[Decimal]
    absolute: Optional[Decimal]