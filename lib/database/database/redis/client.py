from enum import Enum


class ClientSpace(Enum):
    LAST_EXEC = "last-exec"
    USER_ID = "user-id"
    BALANCE = "balance"
    QUERY_PARAMS = "query-params"
    SINCE = "since"
    TO = "to"


class ClientCacheKeys(Enum):
    OVERVIEW = "overview"
    TRADE = "trade"
