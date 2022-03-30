from typing import NamedTuple, Union
from datetime import datetime


class Daily(NamedTuple):
    day: Union[datetime, str]
    amount: float
    diff_absolute: float
    diff_relative: float
