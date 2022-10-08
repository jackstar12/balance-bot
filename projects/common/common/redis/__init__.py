from enum import Enum


class TableNames(Enum):
    CLIENT = "client"
    USER = "user"
    ALERT = "alert"
    BALANCE = "balance"
    TRADE = "trade"
    EVENT = "event"
    TRANSFER = "transfer"
    COIN_STATS = "coinstats"
    TICKER = "ticker"
    PNL = "pnl"
    PNL_DATA = "pnl_data"
    KEYSPACE = "__keyspace@0__"
    CACHE = "cache"


__all__ = [
    "TableNames"
]
