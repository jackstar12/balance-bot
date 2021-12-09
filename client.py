import abc
import discord
import logging
from typing import Optional, List, Optional, Dict, Any


class Client:
    api_key: str
    api_secret: str
    subaccount: str
    exchange = ''
    required_extra_args: List[str] = []

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
    def get_balance(self):
        logging.error(f'Exchange {self.exchange} does not implement get_balance!')

    def repr(self):
        r = f'Exchange: {self.exchange}\n' \
               f'API Key: {self.api_key}\n' \
               f'API secret: {self.api_secret}'
        if self.subaccount != '':
            r += f'\nSubaccount: {self.subaccount}'

        return r

