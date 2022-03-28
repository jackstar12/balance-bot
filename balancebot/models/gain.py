from __future__ import annotations
from typing import NamedTuple, Optional
from balancebot.api.dbmodels.client import Client


class Gain(NamedTuple):
    client: Client
    relative: Optional[float]
    absolute: Optional[float]
