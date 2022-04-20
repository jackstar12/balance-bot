from balancebot.api.dbmodels.serializer import Serializer

from balancebot.api.database import Base, session as session
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, ForeignKey, String, BigInteger, Enum, Table

from balancebot.common.enums import Tier


class Guild(Base, Serializer):
    __tablename__ = 'guild'

    id = Column(BigInteger, primary_key=True, nullable=False)
    name = Column(String, nullable=True)
    tier = Column(Enum(Tier), nullable=False)

    events = relationship('Event', lazy='noload', backref='guild', cascade='all, delete')
    users = relationship('DiscordUser', secondary='guild_association', lazy='noload', backref='guilds')
    global_clients = relationship('GuildAssociation', lazy='noload', backref='guild')
