from enum import Enum


class EventState(Enum):
    ARCHIVED = 1
    REGISTRATION = 2
    OPEN = 3


class Side(Enum):
    BUY = 1
    SELL = -1


class Status(Enum):
    OPEN = 1
    WIN = 2
    LOSS = 3


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


class ExecType(Enum):
    TRADE = 1
    STOP = 3
    TP = 4
    TRANSFER = 2
