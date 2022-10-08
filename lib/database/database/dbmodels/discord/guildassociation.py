from sqlalchemy import Column, ForeignKey
from sqlalchemy.orm import relationship

from database.dbmodels.mixins.serializer import Serializer
from database.dbsync import Base


class GuildAssociation(Base, Serializer):
    __tablename__ = 'guild_association'
    discord_user_id = Column(ForeignKey('oauth_account.account_id', ondelete='CASCADE'), nullable=False, primary_key=True)
    discord_user = relationship('DiscordUser', lazy='raise')

    guild_id = Column(ForeignKey('guild.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    guild = relationship('Guild', lazy='raise')

    client_id = Column(ForeignKey('client.id', ondelete='CASCADE'), nullable=True, primary_key=False)
    client = relationship('Client', lazy='raise')
