from datetime import datetime
from typing import List
import discord

from balancebot import api as client
from balancebot.api.dbmodels.serializer import Serializer

from balancebot.api.database import Base, session as session
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, ForeignKey, String, BigInteger


class DiscordUser(Base, Serializer):
    __tablename__ = 'discorduser'
    __serializer_forbidden__ = ['global_client']

    id = Column(Integer(), primary_key=True)
    user_id = Column(BigInteger(), nullable=False)
    name = Column(String(), nullable=True)
    user = relationship('User', backref='discorduser', lazy=True, uselist=False)
    avatar = Column(String(), nullable=True)

    global_client_id = Column(Integer(), ForeignKey('client.id', ondelete="SET NULL"), nullable=True)
    global_client = relationship('Client', lazy=True, foreign_keys=global_client_id, post_update=True, uselist=False, cascade="all, delete")

    clients = relationship('Client', backref='discorduser', lazy=True, uselist=True, foreign_keys='[Client.discord_user_id]', cascade='all, delete')
    alerts = relationship('Alert', backref='discorduser', lazy=True, cascade="all, delete")

    def get_discord_embed(self) -> List[discord.Embed]:
        return [client.get_discord_embed() for client in self.clients]

    def get_display_name(self, dc_client: discord.Client, guild_id: int):
        try:
            return dc_client.get_guild(guild_id).get_member(self.user_id).display_name
        except AttributeError:
            return None


def add_user_from_json(user_json) -> DiscordUser:
    exchange_name = user_json['exchange'].lower()
    if exchange_name == 'binance':
        exchange_name = 'binance-futures'

    rekt_on = user_json.get('rekt_on', None)
    if rekt_on:
        rekt_on = datetime.fromtimestamp(rekt_on)
    exchange: client.Client = client.Client(
        api_key=user_json['api_key'],
        api_secret=user_json['api_secret'],
        subaccount=user_json['subaccount'],
        extra_kwargs=user_json['extra'],
        rekt_on=rekt_on,
        exchange=exchange_name
    )
    session.add(exchange)
    user = DiscordUser(
        user_id=user_json['id'],
        clients=[exchange],
        global_client=exchange
    )

    session.add(user)
    session.commit()
    return user
