from enum import Enum


class TableNames(Enum):
    CLIENT = "client"
    USER = "user"
    ALERT = "alert"
    BALANCE = "balance"
    TRADE = "trade"
    EVENT = "event"
    TRANSFER = "transfer"
    TICKER = "ticker"
    PNL_DATA = "pnldata"
    CACHE = "cache"
    CHAPTER = "chapter"
    JOURNAL = "journal"


__all__ = [
    "TableNames"
]
