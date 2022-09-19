import enum
from typing import Optional, TypedDict

import sqlalchemy as sa
from aioredis import Redis
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyBaseOAuthAccountTableUUID
from sqlalchemy import Column, ForeignKey, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, backref


from tradealpha.common.models.discord.guild import UserRequest
from tradealpha.common.redis import rpc
from tradealpha.common.dbmodels.mixins.editsmixin import EditsMixin
from tradealpha.common.dbsync import Base
from tradealpha.common.dbmodels.mixins.serializer import Serializer


class Subscription(enum.Enum):
    FREE = 1
    BASIC = 2
    PREMIUM = 3


class OAuthData(TypedDict):
    account_name: str
    avatar_url: str


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    account_id: str = Column(sa.String(length=320), index=True, nullable=False, unique=True)

    data: Optional[OAuthData] = Column(JSONB, nullable=True)

    async def populate_oauth_data(self, redis: Redis) -> Optional[OAuthData]:
        if self.oauth_name == "discord":
            client = rpc.Client('discord', redis)
            try:
                self.data = await client(
                    'user_info', UserRequest(user_id=self.account_id)
                )
            except rpc.Error:
                pass

        return self.data



class User(Base, Serializer, SQLAlchemyBaseUserTableUUID, EditsMixin):
    __tablename__ = 'user'
    __serializer_forbidden__ = ['hashed_password', 'salt']

    oauth_accounts: list[OAuthAccount] = relationship("OAuthAccount", lazy="joined")

    # Identity
    # discord_user_id = Column(BigInteger, ForeignKey('discorduser.id', ondelete='SET NULL'), nullable=True)
    # discord_user = relationship('DiscordUser',
    #                             lazy='noload',
    #                             backref=backref('user', lazy='noload', uselist=False),
    #                             uselist=False, foreign_keys=discord_user_id)

    subscription = Column(sa.Enum(Subscription), default=Subscription.BASIC, nullable=False)
    events = relationship('Event',
                          lazy='raise',
                          back_populates='owner')

    all_clients = relationship(
        'Client',
        lazy='raise',
        primaryjoin='or_('
                    'Client.user_id == User.id,'
                    #'and_(Client.oauth_account_id == OAuthAccount.account_id, OAuthAccount.user_id == User.id)'
                    ')',
        viewonly=True
    )

    # Data
    clients = relationship('Client', back_populates='user', lazy='noload', cascade="all, delete",
                           foreign_keys="[Client.user_id]")

    labels = relationship('Label', backref='user', lazy='raise', cascade="all, delete")
    alerts = relationship('Alert', backref='user', lazy='noload', cascade="all, delete")

    journals = relationship('Journal',
                            back_populates='user',
                            cascade="all, delete",
                            lazy='raise')
    templates = relationship('Template',
                             back_populates='user',
                             cascade="all, delete",
                             lazy='noload')

    def get_oauth(self, name: str):
        for account in self.oauth_accounts:
            if account.oauth_name == name:
                return account

    @property
    def discord_user(self):
        return self.get_oauth('discord')

    @classmethod
    def mock(cls):
        return cls(
            email='mock@gmail.com',
            hashed_password='SUPER_SECURE'
        )

