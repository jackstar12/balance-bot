from sqlalchemy importForeignKey
from sqlalchemy.orm import relationship

from database.dbmodels.mixins.serializer import Serializer
from database.dbsync import Base, BaseMixin


class GuildAssociation(Base, Serializer, BaseMixin):
    __tablename__ = 'guild_association'
    discord_user_id = mapped_column(ForeignKey('oauth_account.account_id', ondelete='CASCADE'), nullable=False, primary_key=True)
    discord_user = relationship('DiscordUser', lazy='raise')

    guild_id = mapped_column(ForeignKey('guild.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    guild = relationship('Guild', lazy='raise')

    client_id = mapped_column(ForeignKey('client.id', ondelete='CASCADE'), nullable=True, primary_key=False)
    client = relationship('Client', lazy='raise')
