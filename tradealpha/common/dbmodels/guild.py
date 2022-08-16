from tradealpha.common.dbmodels.mixins.serializer import Serializer

from tradealpha.common.dbsync import Base
from sqlalchemy.orm import relationship
from sqlalchemy import Column, String, BigInteger, Enum

from tradealpha.common.enums import Tier


class Guild(Base, Serializer):
    __tablename__ = 'guild'

    id = Column(BigInteger, primary_key=True, nullable=False)
    name = Column(String, nullable=True)
    tier = Column(Enum(Tier), default=Tier.BASE, nullable=False)
    avatar = Column(String, nullable=True)

    events = relationship('Event', lazy='noload', backref='guild', cascade='all, delete')
    users = relationship('DiscordUser', secondary='guild_association', lazy='noload', backref='guilds', viewonly=True)
    global_clients = relationship('GuildAssociation', lazy='noload', viewonly=True)
