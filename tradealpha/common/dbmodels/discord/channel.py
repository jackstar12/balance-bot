from tradealpha.common.dbmodels.mixins.serializer import Serializer

from tradealpha.common.dbsync import Base
from sqlalchemy.orm import relationship
from sqlalchemy import Column, String, BigInteger, Enum

from tradealpha.common.enums import Tier


class Channel(Base, Serializer):
    __tablename__ = 'channel'

    id = Column(BigInteger, primary_key=True, nullable=False)
    name = Column(String, nullable=True)
    tier = Column(Enum(Tier), default=Tier.BASE, nullable=False)
    avatar = Column(String, nullable=True)

    events = relationship('Event',
                          lazy='noload',
                          backref='guild',
                          viewonly=True,
                          primaryjoin='Guild.id == foreign(Event.guild_id.cast(BigInteger))')

    users = relationship('DiscordUser', secondary='guild_association', lazy='noload', backref='guilds', viewonly=True)
    global_clients = relationship('GuildAssociation', lazy='noload', viewonly=True)
