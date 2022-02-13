from datetime import datetime

from api.database import db
import discord

from api.dbmodels.client import Client
from api.dbmodels.serializer import Serializer


class DiscordUser(db.Model, Serializer):
    __tablename__ = 'discorduser'
    id = db.Column(db.Integer(), primary_key=True)
    user_id = db.Column(db.BigInteger(), nullable=False)
    name = db.Column(db.String(), nullable=True)

    global_client_id = db.Column(db.Integer(), db.ForeignKey('client.id'))
    global_client = db.relationship('Client', lazy=True, foreign_keys=global_client_id, post_update=True, uselist=False)

    clients = db.relationship('Client', backref='discorduser', lazy=True, uselist=True, foreign_keys='[Client.discord_user_id]')

    def get_discord_embed(self):

        embed = discord.Embed(title="User Information")

        for client in self.clients:
            embed = discord.Embed(title="User Information")
            embed.add_field(name='Event', value=client.get_event_string(), inline=False)
            embed.add_field(name='Exchange', value=client.exchange)
            embed.add_field(name='Api Key', value=client.api_key)
            embed.add_field(name='Api Secret', value=client.api_secret)

            if client.subaccount:
                embed.add_field(name='Subaccount', value=client.subaccount)
            for extra in client.extra_kwargs:
                embed.add_field(name=extra, value=client.extra_kwargs[extra])

            if len(client.history) > 0:
                embed.add_field(name='Initial Balance', value=client.history[0].to_string())

        return embed


def add_user_from_json(user_json) -> DiscordUser:
    exchange_name = user_json['exchange'].lower()
    if exchange_name == 'binance':
        exchange_name = 'binance-futures'

    rekt_on = user_json.get('rekt_on', None)
    if rekt_on:
        rekt_on = datetime.fromtimestamp(rekt_on)
    exchange: Client = Client(
        api_key=user_json['api_key'],
        api_secret=user_json['api_secret'],
        subaccount=user_json['subaccount'],
        extra_kwargs=user_json['extra'],
        rekt_on=rekt_on,
        exchange=exchange_name
    )
    db.session.add(exchange)
    user = DiscordUser(
        user_id=user_json['id'],
        clients=[exchange],
        global_client=exchange
    )
    db.session.add(user)
    db.session.commit()
    return user
