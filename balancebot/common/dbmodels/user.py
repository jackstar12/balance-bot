from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTable
from sqlalchemy import Column, ForeignKey, BigInteger
from sqlalchemy.orm import relationship, backref

from balancebot.common.database import Base
from balancebot.common.dbmodels.serializer import Serializer


class User(Base, Serializer, SQLAlchemyBaseUserTable):
    __tablename__ = 'user'
    __serializer_forbidden__ = ['hashed_password', 'salt']

    # Identity
    # id = Column(Integer, primary_key=True)
    # email = Column(String, unique=True, nullable=False)
    # password = Column(String, unique=True, nullable=False)
    # salt = Column(String, nullable=False)
    discord_user_id = Column(BigInteger(), ForeignKey('discorduser.id', ondelete='SET NULL'), nullable=True)
    discord_user = relationship('DiscordUser', lazy='noload', backref=backref('user', lazy='noload', uselist=False),
                                uselist=False, foreign_keys=discord_user_id)

    all_clients = relationship(
        'Client',
        lazy='raise',
        primaryjoin='or_('
                    'Client.user_id == User.id,'
                    'and_(Client.discord_user_id == User.discord_user_id, User.discord_user_id != None)'
                    ')'
    )

    # Data
    clients = relationship(
        'Client', backref='user', lazy='noload', cascade="all, delete", foreign_keys="[Client.user_id]")
    labels = relationship('Label', backref='client', lazy='noload', cascade="all, delete")
    alerts = relationship('Alert', backref='user', lazy='noload', cascade="all, delete")
