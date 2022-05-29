from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Column, ForeignKey, BigInteger
from sqlalchemy.orm import relationship, backref

from balancebot.common.database import Base
from balancebot.common.dbmodels.serializer import Serializer


class User(Base, Serializer, SQLAlchemyBaseUserTableUUID):
    __tablename__ = 'user'
    __serializer_forbidden__ = ['hashed_password', 'salt']

    # Identity
    discord_user_id = Column(BigInteger, ForeignKey('discorduser.id', ondelete='SET NULL'), nullable=True)
    discord_user = relationship('DiscordUser',
                                lazy='noload',
                                backref=backref('user', lazy='noload', uselist=False),
                                uselist=False, foreign_keys=discord_user_id)

    all_clients = relationship(
        'Client',
        lazy='noload',
        primaryjoin='or_('
                    'Client.user_id == User.id,'
                    'and_(Client.discord_user_id == User.discord_user_id, User.discord_user_id != None)'
                    ')',
        viewonly=True
    )

    # Data
    clients = relationship('Client', back_populates='user', lazy='noload', cascade="all, delete", foreign_keys="[Client.user_id]")
    labels = relationship('Label', backref='user', lazy='noload', cascade="all, delete")
    alerts = relationship('Alert', backref='user', lazy='noload', cascade="all, delete")
    journals = relationship('Journal',
                            back_populates='user',
                            cascade="all, delete",
                            lazy='raise')
