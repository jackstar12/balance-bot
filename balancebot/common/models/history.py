from __future__ import annotations
from typing import NamedTuple, Optional, List
from balancebot.common.dbmodels.balance import Balance


class History(NamedTuple):
    data: List[Balance]
    initial: Optional[Balance]
