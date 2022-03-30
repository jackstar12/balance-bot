from __future__ import annotations
from typing import NamedTuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import balancebot.api.dbmodels.client as c


class Gain(NamedTuple):
    client: c.Client
    relative: Optional[float]
    absolute: Optional[float]
