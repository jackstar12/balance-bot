from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tradealpha.common.dbmodels.client import Client


class Gain(NamedTuple):
    relative: Decimal
    absolute: Decimal


class ClientGain(NamedTuple):
    client: Client
    relative: Optional[Decimal]
    absolute: Optional[Decimal]