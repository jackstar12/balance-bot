from enum import Enum


class Side(Enum):
    BUY = 1
    SELL = 2


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
