from decimal import Decimal
from typing import NamedTuple, Union
from datetime import datetime


class Daily(NamedTuple):
    day: Union[int, str]
    amount: Decimal
    diff_absolute: float
    diff_relative: float
