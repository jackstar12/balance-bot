from __future__ import annotations
import asyncio
import logging
import secrets
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Optional, Union, Literal, Any, TYPE_CHECKING, Sequence, TypedDict, Type
from uuid import UUID
import sqlalchemy as sa
import pytz
from aioredis import Redis
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, PickleType, or_, desc, Boolean, select, func, \
    Date, UniqueConstraint, orm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, reconstructor, RelationshipProperty, declared_attr

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm.dynamic import AppenderQuery
from sqlalchemy.sql import Select, Delete, Update
from sqlalchemy_utils.types.encrypted.encrypted_type import StringEncryptedType, FernetEngine

import os
import dotenv
from typing_extensions import NotRequired

import database.dbmodels as dbmodels
import core
from database.env import environment
from database.errors import UserInputError
from database.dbmodels.transfer import Transfer

from database.dbmodels.mixins.editsmixin import EditsMixin
from core import json as customjson
from database.dbasync import db_first, db_all, db_select_all, redis, redis_bulk_keys, RedisKey, db_unique, \
    time_range
from database.dbmodels.editing.chapter import Chapter
from database.dbmodels.discord.guildassociation import GuildAssociation
from database.dbmodels.pnldata import PnlData
from database.dbmodels.mixins.serializer import Serializer
from database.dbmodels.user import User
from database.models import BaseModel, InputID, OutputID
from database.models.balance import Balance as BalanceModel, Amount
from database.dbsync import Base, BaseMixin, FKey
from database.models.discord.guild import GuildRequest
from database.redis import TableNames, rpc
from database.dbmodels.trade import Trade
from database.redis.client import ClientSpace


class DiscordPermission(TypedDict):
    guild_id: OutputID
    # role_id: NotRequired[OutputID]
    # member_id: NotRequired[OutputID]


class AssociationType(Enum):
    EVENT = 'event'
    CHAPTER = 'chapter'
    TRADE = 'trade'
    JOURNAL = 'journal'

    def get_impl(self) -> Type[GrantAssociaton]:
        if self == AssociationType.EVENT:
            return EventGrant
        elif self == AssociationType.CHAPTER:
            return ChapterGrant
        elif self == AssociationType.JOURNAL:
            return JournalGrant
        elif self == AssociationType.TRADE:
            return TradeGrant


class AuthGrant(Base, BaseMixin):
    __tablename__ = 'authgrant'
    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String, nullable=True)
    user_id = sa.Column(FKey('user.id', ondelete='CASCADE'), nullable=False)
    expires = sa.Column(sa.DateTime(timezone=True), nullable=True)
    public = sa.Column(sa.Boolean, server_default='False', default=False)
    wildcards = sa.Column(sa.ARRAY(sa.Enum(AssociationType)), nullable=True)
    data = sa.Column(sa.JSON, nullable=True)
    _token = sa.Column('token', sa.String, nullable=True)

    user = relationship('User')
    granted_journals = relationship('Journal', secondary='journalgrant', backref='grants')
    granted_events = relationship('Event', secondary='eventgrant', backref='grants')

    def __init__(self, *args, root=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.root = root

    @hybrid_property
    def token(self):
        return self._token

    @token.setter
    def token(self, value: bool):
        if value:
            self._token = secrets.token_urlsafe()
        else:
            self._token = None

    @orm.reconstructor
    def init(self):
        self.root = False

    @property
    def journals(self):
        return self.user.journals if self.is_root_for(AssociationType.JOURNAL) else self.granted_journals

    @property
    def events(self):
        return self.user.events if self.is_root_for(AssociationType.EVENT) else self.granted_events

    @property
    def owner(self):
        return self.sync_session.get(User, self.user_id) if self.sync_session else self.user

    @hybrid_property
    def discord(self) -> DiscordPermission:
        return self.data.get('discord')

    @discord.expression
    def discord(self):
        return self.data['discord']

    @discord.setter
    def discord(self, value: DiscordPermission):
        if value:
            self.data['discord'] = value
        elif self.data:
            self.data.pop('discord')

    def is_root_for(self, assoc_type: AssociationType):
        return self.root or (self.wildcards and assoc_type in self.wildcards)

    async def check_ids(self, asooc_type: AssociationType, ids: Sequence[int] = None):
        impl = asooc_type.get_impl()
        return await db_all(
            select(impl.identity).where(
                impl.grant_id == self.id,
                impl.identity in ids if ids else True
            ),
            session=self.async_session
        )

    async def validate(self):
        await self.check(self.user)

    async def check(self, user: User):
        if user and self.user_id == user.id:
            self.root = True
        if self.data and 'discord' in self.data:
            assert user and user.discord, "No discord account provided"
            client = rpc.Client('discord', redis)
            guild = await client.call('guild',
                                      request=GuildRequest(
                                          user_id=user.discord.account_id,
                                          guild_id=self.discord['guild_id'])
                                      )
            assert guild, "Invalid guild"


class GrantAssociaton(BaseMixin):
    @declared_attr
    def grant_id(self):
        return sa.Column(FKey('authgrant.id', ondelete='CASCADE'), primary_key=True)

    @declared_attr
    def grant(self):
        return orm.relationship(AuthGrant, lazy='raise')

    @hybrid_property
    def identity(cls):
        raise NotImplementedError

    @identity.setter
    def identity(self, val):
        raise NotImplementedError


class EventGrant(Base, GrantAssociaton):
    __tablename__ = 'eventgrant'

    event_id = sa.Column(FKey('event.id', ondelete='CASCADE'), primary_key=True)
    registrations_left = sa.Column(sa.Integer, nullable=True)

    @hybrid_property
    def identity(cls):
        return cls.event_id

    @identity.setter
    def identity(self, val):
        self.event_id = val


class JournalGrant(Base, GrantAssociaton):
    __tablename__ = 'journalgrant'
    journal_id = sa.Column(FKey('journal.id', ondelete='CASCADE'), primary_key=True)

    @hybrid_property
    def identity(cls):
        return cls.journal_id

    @identity.setter
    def identity(self, val):
        self.journal_id = val


class ChapterGrant(Base, GrantAssociaton):
    __tablename__ = 'chaptergrant'
    chapter_id = sa.Column(FKey('chapter.id', ondelete='CASCADE'), primary_key=True)

    @hybrid_property
    def identity(cls):
        return cls.chapter_id

    @identity.setter
    def identity(self, val):
        self.chapter_id = val


class TradeGrant(Base, GrantAssociaton):
    __tablename__ = 'tradegrant'
    trade_id = sa.Column(FKey('trade.id', ondelete='CASCADE'), primary_key=True)

    @hybrid_property
    def identity(cls):
        return cls.trade_id

    @identity.setter
    def identity(self, val):
        self.trade_id = val
