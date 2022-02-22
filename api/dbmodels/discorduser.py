from datetime import datetime
from typing import List

from api.database import db
import discord

from api.dbmodels.client import Client
from api.dbmodels.serializer import Serializer


class DiscordUser(db.Model, Serializer):
    __tablename__ = 'discorduser'
    id = db.Column(db.Integer(), primary_key=True)
    user_id = db.Column(db.BigInteger(), nullable=False)
    name = db.Column(db.String(), nullable=True)
    user = db.relationship('User', backref='discorduser', lazy=True, uselist=False)
    avatar = db.Column(db.String(), nullable=True)

    global_client_id = db.Column(db.Integer(), db.ForeignKey('client.id', ondelete="SET NULL"), nullable=True)
    global_client = db.relationship(
        'Client',
        lazy=True,
        foreign_keys=global_client_id,
        post_update=True,
        primaryjoin='Client.id == DiscordUser.global_client_id',
        uselist=False
    )

    clients = db.relationship(
        'Client',
        backref='discorduser',
        lazy=True,
        uselist=True,
        foreign_keys='[Client.discord_user_id]',
        cascade='all, delete-orphan'
    )

    def get_discord_embed(self) -> List[discord.Embed]:
        return [client.get_discord_embed() for client in self.clients]


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
