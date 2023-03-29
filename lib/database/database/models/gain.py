from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import NamedTuple, Optional, TYPE_CHECKING

from core.utils import round_ccy
from database.models import BaseModel

if TYPE_CHECKING:
    from database.dbmodels.client import Client


class Gain(BaseModel):
    relative: Decimal
    absolute: Decimal
    currency: Optional[str]

    def to_string(self, ccy: str):
        return f'{round_ccy(self.relative, "%")}% ({round_ccy(self.absolute, ccy)}{ccy})'



class ClientGain(NamedTuple):
    client: Client
    relative: Decimal
    absolute: Decimal
