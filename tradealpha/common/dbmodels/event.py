from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

import pytz
import sqlalchemy.exc
from aioredis import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.common.dbutils import get_client_history
from tradealpha.common.models import OrmBaseModel
from tradealpha.common.dbmodels.discord.discorduser import DiscordUser, get_display_name
from tradealpha.common.utils import join_args
from tradealpha.common.dbmodels.score import EventScore, EventRank
from tradealpha.common.models.discord.guild import GuildRequest
from tradealpha.common.redis import rpc
from tradealpha.common.dbmodels.types import Document
import numpy
from tradealpha.common.dbmodels.archive import Archive
from tradealpha.common.dbmodels.mixins.serializer import Serializer
from datetime import datetime
from sqlalchemy.ext.hybrid import hybrid_property
import discord

from tradealpha.common.dbsync import Base
from sqlalchemy.orm import relationship, backref
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, inspect, Boolean, func, desc, \
    select, insert, literal, and_, update, Numeric

if TYPE_CHECKING:
    from tradealpha.common.dbmodels.user import User
    from tradealpha.common.dbmodels.client import Client

event_association = 'eventscore'


class LocationModel(OrmBaseModel):
    platform: str
    data: dict


class EventState(Enum):
    UPCOMING = "upcoming"
    ACTIVE = "active"
    REGISTRATION = "registration"
    ARCHIVED = "archived"


class Stat(OrmBaseModel):
    best: UUID
    worst: UUID

    @classmethod
    def from_sorted(cls, sorted_clients: list[EventScore]):
        return cls(
            best=sorted_clients[0].client.user_id,
            worst=sorted_clients[-1].client.user_id,
        )


class Summary(OrmBaseModel):
    gain: Stat
    stakes: Stat
    volatility: Stat
    avg_percent: Decimal
    total: Decimal


Location = LocationModel.get_sa_type()


class Event(Base, Serializer):
    __tablename__ = 'event'
    __serializer_forbidden__ = ['archive']

    id = Column(Integer, primary_key=True)

    owner_id = Column(ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    registration_start = Column(DateTime(timezone=True), nullable=False)
    registration_end = Column(DateTime(timezone=True), nullable=False)
    start = Column(DateTime(timezone=True), nullable=False)
    end = Column(DateTime(timezone=True), nullable=False)
    max_registrations = Column(Integer, nullable=False, default=100)
    allow_transfers = Column(Boolean, default=False)

    name = Column(String, nullable=False)
    description = Column(Document, nullable=False)
    public = Column(Boolean, default=False, nullable=False)
    location = Column(Location, nullable=False)
    currency = Column(String(10), nullable=False, server_default='USD')
    rekt_threshold = Column(Numeric, nullable=False, server_default='-99')

    owner: User = relationship('User', lazy='noload')

    registrations: list[Client] = relationship('Client',
                                               lazy='raise',
                                               secondary=event_association,
                                               backref=backref('events', lazy='noload'))

    leaderboard: list[EventScore] = relationship('EventScore',
                                                 lazy='raise',
                                                 back_populates='event',
                                                 order_by="and_(desc(EventScore.rel_value), EventScore.rekt_on)")

    archive = relationship('Archive',
                           backref=backref('event', lazy='noload'),
                           uselist=False,
                           cascade="all, delete")

    @hybrid_property
    def all_clients(self):
        try:
            return self.registrations
        except sqlalchemy.exc.InvalidRequestError:
            return [score.client for score in self.leaderboard]

    @hybrid_property
    def state(self):
        now = datetime.now(pytz.utc)
        res = []
        if self.registration_start > now:
            res.append(EventState.UPCOMING)
        if self.end < now:
            res.append(EventState.ARCHIVED)
        if self.start <= now <= self.end:
            res.append(EventState.ACTIVE)
        if self.registration_start <= now <= self.registration_end:
            res.append(EventState.REGISTRATION)
        return res

    def is_(self, state: EventState):
        return state in self.state

    @classmethod
    def is_expr(cls, state: EventState):
        now = func.now()
        if state == EventState.ARCHIVED:
            return cls.end < func.now()
        elif state == EventState.ACTIVE:
            return and_(cls.start <= now, now <= cls.end)
        elif state == EventState.REGISTRATION:
            return and_(cls.registration_start <= now, now <= cls.registration_end)
        else:
            return False

    def validate(self):
        if self.start >= self.end:
            raise ValueError("Start time can't be after end time.")
        if self.registration_start >= self.registration_end:
            raise ValueError("Registration start can't be after registration end")
        if self.registration_end < self.start:
            raise ValueError("Registration end should be after or at event start")
        if self.registration_end > self.end:
            raise ValueError("Registration end can't be after event end.")
        if self.registration_start > self.start:
            raise ValueError("Registration start should be before event start.")
        if self.max_registrations < len(self.all_clients):
            raise ValueError("Max Registrations can not be less than current registration count")

    async def validate_location(self, redis: Redis):
        self.location: 'LocationModel'
        if self.location.platform == 'discord':
            # Validate
            discord_oauth = self.owner.get_oauth('discord')
            if not discord:
                raise ValueError("No discord account")
            client = rpc.Client('discord', redis)
            guild = await client(
                'guild', GuildRequest(
                    user_id=discord_oauth.account_id,
                    guild_id=self.location.data['guild_id']
                )
            )
            if all(ch['id'] != self.location.data['channel_id'] for ch in guild['text_channels']):
                raise ValueError("Invalid channel")

    @property
    def key(self):
        return join_args(self.__tablename__, self.id)

    @property
    def leaderboard_key(self):
        return join_args(self.key, 'leaderboard')

    @classmethod
    async def save_leaderboard(cls, event_id: int, db: AsyncSession):

        ranks = select(
            EventScore.client_id,
            func.rank().over(
                order_by=desc(EventScore.rel_value)
            ).label('value')
        ).where(
            EventScore.event_id == event_id
        ).subquery()

        now = datetime.now(pytz.utc)

        stmt = select(
            literal(event_id).label('event_id'),
            literal(now).label('time'),
            ranks.c.client_id,
            ranks.c.value
        )
        # .join(
        #     EventRank, and_(
        #     )
        #     EventScore.current_rank
        # ).where(
        #     or_(
        #         ~EventScore.last_rank_update,
        #         EventRank.value != ranks.c.values
        #     )
        # )

        result = await db.execute(
            insert(EventRank).from_select(
                ["event_id", "time", "client_id", "value"],
                stmt
            ).returning(
                EventRank.client_id
            )
        )

        await db.execute(
            update(EventScore).values(
                last_rank_update=now
            ).where(
                EventScore.client_id.in_(row[0] for row in result)
            )
        )

    @hybrid_property
    def guild_id(self):
        return self.location.data['guild_id']

    @guild_id.expression
    def guild_id(self):
        return self.location['data']['guild_id']

    @hybrid_property
    def channel_id(self):
        return self.location.data['channel_id']

    @channel_id.expression
    def channel_id(self):
        return self.location['data']['channel_id']

    @hybrid_property
    def is_active(self):
        return self.is_(EventState.ACTIVE)

    def is_free_for_registration(self):
        return self.is_(EventState.REGISTRATION)

    @hybrid_property
    def is_full(self):
        return len(self.registrations) < self.max_registrations

    def get_discord_embed(self, title: str, dc_client: discord.Client, registrations=False):
        embed = discord.Embed(title=title)
        embed.add_field(name="Name", value=self.name)
        # embed.add_field(name="Description", value=self.description)
        embed.add_field(name="Start", value=self.start, inline=False)
        embed.add_field(name="End", value=self.end)
        embed.add_field(name="Registration Start", value=self.registration_start, inline=False)
        embed.add_field(name="Registration End", value=self.registration_end)

        if registrations:
            value = '\n'.join(
                f'{get_display_name(dc_client, int(score.client.user.discord_user.account_id), self.guild_id)}'
                for score in self.leaderboard
            )

            embed.add_field(name="Registrations", value=value if value else 'Be the first!', inline=False)

            # self._archive.registrations = value

        return embed

    async def get_summary(self) -> Summary:

        gain = Stat.from_sorted(self.leaderboard)
        stakes = Stat.from_sorted(sorted(self.leaderboard, key=lambda x: x.init_balance.realized, reverse=True))

        async def vola(client: Client):
            history = await get_client_history(client, self.start, self.start, self.end)
            return numpy.array([
                balance.unrealized
                for balance in history.data if balance.unrealized
            ]).std() / history.data[0].unrealized

        client_vola = [
            (client, await vola(client))
            for client in self.all_clients
        ]
        client_vola.sort(key=lambda x: x[1], reverse=True)

        volatili = Stat(
            best=client_vola[0][0].user_id,
            worst=client_vola[-1][0].user_id,
        )

        cum_percent = Decimal(0)
        cum_dollar = Decimal(0)
        for score in self.leaderboard:
            cum_percent += score.rel_value
            cum_dollar += score.abs_value

        cum_percent /= len(self.leaderboard) or 1  # Avoid division by zero

        return Summary(
            gain=gain, stakes=stakes, volatility=volatili, avg_percent=cum_percent, total=cum_dollar
        )

    @property
    def _archive(self):
        if not self.archive:
            self.archive = Archive(event_id=self.id)
            inspect(self).session.add(self.archive)
        return self.archive

    def __hash__(self):
        return self.id.__hash__()
