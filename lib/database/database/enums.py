from enum import Enum


class IntervalType(Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class TradeSession(Enum):
    ASIA = "asia"
    LONDON = "london"
    NEW_YORK = "new_york"


class Side(Enum):
    BUY = 'buy'
    SELL = 'sell'


class Status(Enum):
    OPEN = 0
    WIN = 1
    LOSS = -1


class TimeFrame(Enum):
    M1 = 1
    M5 = 2
    M15 = 3
    H1 = 4
    H4 = 5
    D = 6
    W = 7
    M = 8


class Tier(Enum):
    BASE = 1
    PREMIUM = 2


class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    FORCE = 4


class Filter(Enum):
    WEEKDAY = "weekday"
    SESSION = "session"
    LABEL = "label"


class MarketType(Enum):
    SPOT = "spot"
    DERIVATIVES = "derivatives"


class ExecType(Enum):
    TRADE = "trade"
    TRANSFER = "transfer"
    FUNDING = "funding"
    LIQUIDATION = "liquidation"
    STOP = "stop"
    TP = "tp"
