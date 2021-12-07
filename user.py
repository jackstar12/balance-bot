import dataclasses
import discord
from client import Client
from datetime import datetime


@dataclasses.dataclass
class User:
    id: int
    api: Client
    rekt_on: datetime = None

    def __hash__(self):
        return self.id.__hash__()

    def get_discord_embed(self):
        embed = discord.Embed(title="User Information")

        embed.add_field(name='Exchange', value=self.api.exchange)
        embed.add_field(name='API Key', value=self.api.api_key)
        embed.add_field(name='API Secret', value=self.api.api_secret)
        if self.api.subaccount:
            embed.add_field(name='Subaccount', value=self.api.subaccount)
        for extra in self.api.extra_kwargs:
            embed.add_field(name=extra, value=self.api.extra_kwargs[extra])

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
        return json


