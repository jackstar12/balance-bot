from enum import Enum

from tradealpha.common import utils
from tradealpha.common.messenger import Word


class ClientSpace(Enum):
    LAST_EXEC = "last-exec"
    USER_ID = "user-id"
    BALANCE = "balance"


class ClientCache(Enum):
    OVERVIEW = "overview"
    OVERVIEW_EXEC_TS = utils.join_args(OVERVIEW, ClientSpace.LAST_EXEC)
