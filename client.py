import abc
import dataclasses
from typing import overload


@dataclasses.dataclass
class Client:
    api_key = ''
    api_secret = ''
    subaccount = ''
    exchange = ''

    @abc.abstractmethod
    def getBalance(self):
        # Has to be implemented for specific exchange
        raise NotImplementedError()
