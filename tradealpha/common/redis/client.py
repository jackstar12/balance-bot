from enum import Enum

from tradealpha.common import utils
from tradealpha.common.messenger import Word


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
