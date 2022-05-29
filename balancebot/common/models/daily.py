from decimal import Decimal
from typing import NamedTuple, Union
from datetime import datetime, date
from typing import TYPE_CHECKING

from balancebot.common.dbmodels.balance import Balance


class Daily(NamedTuple):
    day: Union[int, str]
    amount: Decimal
    diff_absolute: Decimal
    diff_relative: Decimal


class Interval(NamedTuple):
    day: Union[date, str]
    amount: Decimal
    diff_absolute: Decimal
    diff_relative: Decimal
    start_balance: Balance
    end_balance: Balance



