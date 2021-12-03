import dataclasses
import discord
from client import Client


@dataclasses.dataclass
class User:
    id: int
    api: Client

    def get_discord_embed(self):
        embed = discord.Embed(title="User Information")

        embed.add_field(name='Exchange', value=self.api.exchange)
        embed.add_field(name='API Key', value=self.api.api_key)
        embed.add_field(name='API Secret', value=self.api.api_secret)
        if self.api.subaccount is not None:
            embed.add_field(name='Subaccount', value=self.api.subaccount)

        return embed

    def to_json(self):
        return {
            'id': self.id,
            'exchange': self.api.exchange,
            'api_key': self.api.api_key,
            'api_secret': self.api.api_secret,
            'subaccount': self.api.subaccount
        }

