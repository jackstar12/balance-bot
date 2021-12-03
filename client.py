import abc
import dataclasses
import discord
from typing import overload

@dataclasses.dataclass
class Client:
    api_key: str
    api_secret: str
    subaccount: str
    exchange = ''

    @abc.abstractmethod
    def getBalance(self):
        # Has to be implemented for specific exchange
        raise NotImplementedError()

    def repr(self):
        repr = f'Exchange: {self.exchange}\n' \
               f'API Key: {self.api_key}\n' \
               f'API secret: {self.api_secret}'
        if self.exchange != '':
            repr += f'\nSubaccount: {self.subaccount}'
        return repr

