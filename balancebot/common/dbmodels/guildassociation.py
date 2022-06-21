from balancebot.common.dbsync import Base
from sqlalchemy import Column, ForeignKey, BigInteger

from balancebot.common.dbmodels.serializer import Serializer


class GuildAssociation(Base, Serializer):
    __tablename__ = 'guild_association'
    client_id = Column(ForeignKey('client.id', ondelete='CASCADE'), nullable=True, primary_key=True)
    discord_user_id = Column(BigInteger, ForeignKey('discorduser.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild.id', ondelete='CASCADE'), nullable=False, primary_key=True)
