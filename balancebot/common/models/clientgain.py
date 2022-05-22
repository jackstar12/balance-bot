from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from balancebot.common.dbmodels.client import Client


class Gain(NamedTuple):
    relative: Optional[Decimal]
    absolute: Optional[Decimal]


class ClientGain(NamedTuple):
    client: Client
    relative: Optional[Decimal]
    absolute: Optional[Decimal]
