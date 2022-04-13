from typing import NamedTuple, Union
from datetime import datetime


class Daily(NamedTuple):
    day: Union[int, str]
    amount: float
    diff_absolute: float
    diff_relative: float
