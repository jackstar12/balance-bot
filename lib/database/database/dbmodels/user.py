from __future__ import annotations
import enum
import sqlalchemy as sa

from typing import Optional, TypedDict, TYPE_CHECKING
from aioredis import Redis
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyBaseOAuthAccountTableUUID
from sqlalchemy import Column, orm
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from database.dbmodels.mixins.editsmixin import EditsMixin
from database.dbmodels.mixins.serializer import Serializer
from database.dbmodels.types import Document
from database.dbsync import Base
from database.models.user import ProfileData, UserProfile

if TYPE_CHECKING:
    from database.dbmodels.discord.discorduser import DiscordUser


class Subscription(enum.Enum):
    FREE = 1
    BASIC = 2
    PREMIUM = 3


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    account_id: str = Column(sa.String(length=320), index=True, nullable=False, unique=True)
    data: Optional[ProfileData] = Column(JSONB, nullable=True)

    __mapper_args__ = {
        "polymorphic_on": "oauth_name",
    }

    async def populate_oauth_data(self, redis: Redis) -> Optional[ProfileData]:
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

    info: str | ProfileData | None = Column(JSONB, nullable=True)
    about_me = Column(Document, nullable=True)
    events = relationship('Event',
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
    clients = relationship('Client',
                           back_populates='user',
                           lazy='noload',
                           cascade="all, delete",
                           foreign_keys="[Client.user_id]")

    label_groups = relationship('LabelGroup', backref='user', lazy='raise', cascade="all, delete")
    alerts = relationship('Alert', backref='user', lazy='noload', cascade="all, delete")

    journals = relationship('Journal',
                            back_populates='user',
                            cascade="all, delete")

    templates = relationship('Template',
                             back_populates='user',
                             cascade="all, delete")

    def get_oauth(self, name: str) -> Optional[OAuthAccount]:
        for account in self.oauth_accounts:
            if account.oauth_name == name:
                return account

    @property
    def profile(self) -> UserProfile:
        src = None
        if isinstance(self.info, str):
            data = self.get_oauth(self.info).data
            src = self.info
        else:
            data = self.info
        if not data:
            data = ProfileData(
                name=self.email,
                avatar_url='',
            )
        return UserProfile(
            **data,
            src=src
        )

    @property
    def discord(self) -> Optional[DiscordUser]:
        return self.get_oauth('discord')

    @classmethod
    def mock(cls):
        return cls(
            email='mock@gmail.com',
            hashed_password='SUPER_SECURE'
        )

