import abc
import discord
from typing import Optional, List, Optional, Dict, Any


class Client:
    api_key: str
    api_secret: str
    subaccount: str
    exchange = ''

    def __init__(self,
                 api_key: str,
                 api_secret: str,
                 subaccount: Optional[str] = None,
                 extra_kwargs: Optional[Dict[str, Any]] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.subaccount = subaccount
        self.extra_kwargs = extra_kwargs

    @abc.abstractmethod
    def getBalance(self):
        # Has to be implemented for specific exchange
        raise NotImplementedError()

    def repr(self):
        r = f'Exchange: {self.exchange}\n' \
               f'API Key: {self.api_key}\n' \
               f'API secret: {self.api_secret}'
        if self.subaccount != '':
            r += f'\nSubaccount: {self.subaccount}'

        return r

