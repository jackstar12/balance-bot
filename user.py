import dataclasses
import discord
import logging
from client import Client
from datetime import datetime
from balance import Balance
from typing import Tuple, Dict, List, Type


@dataclasses.dataclass
class User:
    id: int
    api: Client
    rekt_on: datetime = None
    initial_balance: Tuple[datetime, Balance] = None
    guild_id: int = None

    def __hash__(self):
        return self.id.__hash__()

    def get_discord_embed(self, guild_name: str = None):
        embed = discord.Embed(title="User Information")

        embed.add_field(name='Guild', value=guild_name if guild_name else 'Global', inline=False)
        embed.add_field(name='Exchange', value=self.api.exchange)
        embed.add_field(name='API Key', value=self.api.api_key)
        embed.add_field(name='API Secret', value=self.api.api_secret)

        if self.api.subaccount:
            embed.add_field(name='Subaccount', value=self.api.subaccount)
        for extra in self.api.extra_kwargs:
            embed.add_field(name=extra, value=self.api.extra_kwargs[extra])

        if self.initial_balance:
            embed.add_field(name='Initial Balance', value=self.initial_balance[1].to_string())

        return embed

    def to_json(self):
        json = {
            'id': self.id,
            'exchange': self.api.exchange,
            'api_key': self.api.api_key,
            'api_secret': self.api.api_secret,
            'subaccount': self.api.subaccount,
            'extra': self.api.extra_kwargs
        }
        if self.rekt_on:
            json['rekt_on'] = self.rekt_on.timestamp()
        if self.initial_balance:
            json['initial_balance'] = {
                'date': self.initial_balance[0].timestamp(),
                'amount': self.initial_balance[1].amount
            }
        if self.guild_id:
            json['guild_id'] = self.guild_id

        return json


def user_from_json(user_json, exchange_classes: Dict[str, Type[Client]], initial_balance_default: Tuple[datetime, Balance] = None) -> User:
    exchange_name = user_json['exchange'].lower()
    exchange_cls = exchange_classes[exchange_name]
    if issubclass(exchange_cls, Client):
        exchange: Client = exchange_cls(
            api_key=user_json['api_key'],
            api_secret=user_json['api_secret'],
            subaccount=user_json['subaccount'],
            extra_kwargs=user_json['extra']
        )
        rekt_on = user_json.get('rekt_on', None)
        if rekt_on:
            rekt_on = datetime.fromtimestamp(rekt_on)
        initial_balance = user_json.get('initial_balance', None)
        if initial_balance:
            initial_balance = (
                datetime.fromtimestamp(initial_balance['date']),
                Balance(amount=initial_balance['amount'], currency='$', error=None)
            )
        elif initial_balance_default:
            initial_balance = initial_balance_default

        user = User(
            id=user_json['id'],
            api=exchange,
            rekt_on=rekt_on,
            initial_balance=initial_balance,
            guild_id=user_json.get('guild_id', None)
        )
        return user
    else:
        logging.error(f'{exchange_cls} is no subclass of client!')
