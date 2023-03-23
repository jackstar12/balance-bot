from __future__ import annotations
import enum
import uuid

import sqlalchemy as sa

from typing import Optional, TypedDict, TYPE_CHECKING, Generic
from aioredis import Redis
from fastapi_users.models import ID
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyBaseOAuthAccountTableUUID, UUID_ID, GUID
from sqlalchemy import String, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, mapped_column, Mapped, declared_attr, declarative_mixin

from database.dbmodels.mixins.editsmixin import EditsMixin
from database.dbmodels.mixins.serializer import Serializer
from database.dbmodels.types import Document
from database.dbsync import Base, BaseMixin
from database.models.document import DocumentModel
from database.models.user import ProfileData, UserProfile

if TYPE_CHECKING:
    from database.dbmodels.discord.discorduser import DiscordUser


class Subscription(enum.Enum):
    FREE = 1
    BASIC = 2
    PREMIUM = 3


@declarative_mixin
class SQLAlchemyBaseUserTable(Generic[ID]):
    """Base SQLAlchemy users table definition."""

    __tablename__ = "user"

    oauth_name: Mapped[str] = mapped_column(String(length=100), index=True, nullable=False)
    access_token: Mapped[str] = mapped_column(String(length=1024), nullable=False)
    expires_at: Mapped[Optional[int]]
    refresh_token: Mapped[Optional[str]] = mapped_column(String(length=1024), nullable=True)
    account_id: Mapped[str] = mapped_column(String(length=320), index=True, nullable=False)


@declarative_mixin
class SQLAlchemyBaseUserTableUUID(SQLAlchemyBaseUserTable[UUID_ID]):
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)


@declarative_mixin
class SQLAlchemyBaseOAuthAccountTable(Generic[ID]):
    """Base SQLAlchemy OAuth account table definition."""

    __tablename__ = "oauth_account"
    oauth_name: Mapped[str] = mapped_column(String(length=100), index=True, nullable=False)
    access_token: Mapped[str] = mapped_column(String(length=1024), nullable=False)
    expires_at: Mapped[Optional[int]]
    refresh_token: Mapped[Optional[str]] = mapped_column(String(length=1024), nullable=True)
    account_id: Mapped[str] = mapped_column(String(length=320), index=True, nullable=False)
    account_email: Mapped[str] = mapped_column(String(length=320), nullable=False)


@declarative_mixin
class SQLAlchemyBaseOAuthAccountTableUUID(SQLAlchemyBaseOAuthAccountTable[UUID_ID]):
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)

    @declared_attr
    def user_id(cls) -> Mapped[GUID]:
        return mapped_column(GUID, ForeignKey("user.id", ondelete="cascade"), nullable=False)


class OAuthAccount(Base, Serializer, BaseMixin, SQLAlchemyBaseOAuthAccountTableUUID):
    __tablename__ = 'oauth_account'
    __allow_unmapped__ = True

    account_id: Mapped[str] = mapped_column(sa.String(length=320), index=True, nullable=False, unique=True)
    data: Mapped[Optional[ProfileData]] = mapped_column(JSONB, nullable=True)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('user.id', ondelete='cascade'), nullable=False)

    __mapper_args__ = {
        "polymorphic_on": "oauth_name",
    }

    async def populate_oauth_data(self, redis: Redis) -> Optional[ProfileData]:
        return self.data


class User(Base, Serializer, BaseMixin, SQLAlchemyBaseUserTableUUID, EditsMixin):
    __allow_unmapped__ = True
    __tablename__ = 'user'
    __serializer_forbidden__ = ['hashed_password', 'salt']

    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(lazy="joined")

    # Identity
    # discord_user_id = mapped_column(BigInteger, ForeignKey('discorduser.id', ondelete='SET NULL'), nullable=True)
    # discord_user = relationship('DiscordUser',
    #                             lazy='noload',
    #                             backref=backref('user', lazy='noload', uselist=False),
    #                             uselist=False, foreign_keys=discord_user_id)

    subscription: Mapped[Subscription] = mapped_column(sa.Enum(Subscription), default=Subscription.BASIC,
                                                       nullable=False)

    info: Mapped[str | ProfileData | None] = mapped_column(JSONB, nullable=True)
    about_me: Mapped[DocumentModel] = mapped_column(Document, nullable=True)
    events: Mapped[list['Event']] = relationship(back_populates='owner')

    all_clients: Mapped[list['Client']] = relationship(
        lazy='raise',
        primaryjoin='or_('
                    'Client.user_id == User.id,'
        # 'and_(Client.oauth_account_id == OAuthAccount.account_id, OAuthAccount.user_id == User.id)'
                    ')',
        viewonly=True
    )

    # Data
    clients: Mapped[list['Client']] = relationship(back_populates='user',
                                                   lazy='noload',
                                                   cascade="all, delete",
                                                   foreign_keys="[Client.user_id]")

    label_groups: Mapped[list['LabelGroup']] = relationship(backref='user', lazy='raise',
                                                            cascade="all, delete")
    alerts: Mapped[list['Alert']] = relationship(backref='user', lazy='noload', cascade="all, delete")

    journals: Mapped[list['Journal']] = relationship(back_populates='user',
                                                     cascade="all, delete")

    templates: Mapped[list['Template']] = relationship(back_populates='user',
                                                       cascade="all, delete")

    def get_oauth(self, name: str) -> Optional[OAuthAccount]:
        for account in self.oauth_accounts:
            if account.oauth_name == name:
                return account

    @property
    def profile(self) -> UserProfile:
        src = None
        if isinstance(self.info, str):
            account = self.get_oauth(self.info)
            if account:
                data = account.data
                src = self.info
            else:
                data = None
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
