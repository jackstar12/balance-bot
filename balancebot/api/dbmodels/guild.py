from datetime import datetime
from typing import List
import discord

from balancebot import api as client
from balancebot.api.dbmodels.discorduser import DiscordUser
from balancebot.api.dbmodels.serializer import Serializer

from balancebot.api.database import Base, session as session
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, ForeignKey, String, BigInteger, Enum, Table

from balancebot.common.enums import Tier


guild_association = Table('guild_association', Base.metadata,
                          Column('guild_id', BigInteger, ForeignKey('guild.id', ondelete='CASCADE'), primary_key=True),
                          Column('user_id', BigInteger, ForeignKey('discorduser.id', ondelete='CASCADE'), primary_key=True)
                          )


class Guild(Base, Serializer):
    __tablename__ = 'guild'

    id = Column(BigInteger, primary_key=True, nullable=False)
    name = Column(String, nullable=True)
    tier = Column(Enum(Tier), nullable=False)

    events = relationship('Event', lazy=True, backref='guild')
    users = relationship('DiscordUser', secondary=guild_association, lazy=True, backref='guilds')
