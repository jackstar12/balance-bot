from __future__ import annotations
from typing import NamedTuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from balancebot.common.dbmodels.client import Client


class Gain(NamedTuple):
    client: Client
    relative: Optional[float]
    absolute: Optional[float]
