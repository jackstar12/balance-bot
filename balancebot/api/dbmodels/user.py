from sqlalchemy import Column, Integer, ForeignKey, String
from sqlalchemy.orm import relationship

from balancebot.api.database import Base
from balancebot.api.dbmodels.serializer import Serializer


class User(Base, Serializer):
    __tablename__ = 'user'
    __serializer_forbidden__ = ['password', 'salt']

    # Identity
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, unique=True, nullable=False)
    salt = Column(String, nullable=False)
    discord_user_id = Column(Integer(), ForeignKey('discorduser.id', ondelete='SET NULL'), nullable=True)

    # Data
    #main_client_id = Column(Integer, ForeignKey('client.id', ondelete="SET NULL"), nullable=True)
    #main_client = relationship('Client',
    #                           lazy=True,
    #                           cascade="all, delete",
    #                           foreign_keys=main_client_id,
    #                           post_update=True,
    #                           uselist=False)
    clients = relationship('Client', backref='user', lazy=True, cascade="all, delete", foreign_keys="[Client.user_id]")
    labels = relationship('Label', backref='client', lazy=True, cascade="all, delete")
    alerts = relationship('Alert', backref='user', lazy=True, cascade="all, delete")
