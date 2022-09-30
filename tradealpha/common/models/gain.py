from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple, Optional, TYPE_CHECKING

from common.utils import round_ccy
from tradealpha.common import config
from tradealpha.common.models import BaseModel

if TYPE_CHECKING:
    from tradealpha.common.dbmodels.client import Client


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
