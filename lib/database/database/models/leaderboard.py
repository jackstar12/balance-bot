from decimal import Decimal
from enum import Enum
from typing import NamedTuple
from uuid import UUID

from database.models import BaseModel


class LeaderboardType(Enum):
    BALANCE = 'balance'
    PERCENTAGE = 'percentage'


class Score(NamedTuple):
    value: Decimal
    user_id: UUID


class Leaderboard(BaseModel):
    type: LeaderboardType
    scores: list[Score]
