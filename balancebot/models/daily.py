from typing import NamedTuple
from datetime import datetime


class Daily(NamedTuple):
    day: datetime
    amount: float
    diff_absolute: float
    diff_relative: float
