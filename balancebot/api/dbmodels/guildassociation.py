from balancebot.api.database import Base, session as session
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, ForeignKey, String, BigInteger, Enum, Table

from balancebot.api.dbmodels.serializer import Serializer


class GuildAssociation(Base, Serializer):
    __tablename__ = 'guild_association'
    client_id = Column(ForeignKey('client.id', ondelete='CASCADE'), nullable=True, primary_key=True)
    discorduser_id = Column(BigInteger, ForeignKey('discorduser.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild.id', ondelete='CASCADE'), nullable=False, primary_key=True)
