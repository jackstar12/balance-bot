from __future__ import annotations
from typing import TYPE_CHECKING
import utils
import numpy
from models.gain import Gain
from api.database import db
from api.dbmodels.archive import Archive
from datetime import datetime
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
from config import DATA_PATH
import discord


if TYPE_CHECKING:
    from api.dbmodels.client import Client


association = db.Table('association',
                       db.Column('event_id', db.Integer, db.ForeignKey('event.id', ondelete="CASCADE"), primary_key=True),
                       db.Column('client_id', db.Integer, db.ForeignKey('client.id', ondelete="CASCADE"), primary_key=True)
                       )


class Event(db.Model):
    __tablename__ = 'event'
    id = db.Column(db.Integer, primary_key=True)
    guild_id = db.Column(db.BigInteger, nullable=False)
    channel_id = db.Column(db.BigInteger, nullable=False)
    registration_start = db.Column(db.DateTime, nullable=False)
    registration_end = db.Column(db.DateTime, nullable=False)
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)
    name = db.Column(db.String, nullable=False)
    description = db.Column(db.String, nullable=False)

    registrations = db.relationship('Client', secondary=association, backref='events')
    archive = db.relationship('Archive', backref='event', uselist=False, cascade="all, delete")

    @hybrid_property
    def is_active(self):
        return self.start <= datetime.now() <= self.end

    @hybrid_property
    def is_free_for_registration(self):
        return self.registration_start <= datetime.now() <= self.registration_end

    @hybrid_property
    def is_archived(self):
        return self.end < datetime.now()

    def get_discord_embed(self, dc_client: discord.Client, registrations=False):
        embed = discord.Embed(title=f'Event')
        embed.add_field(name="Name", value=self.name)
        embed.add_field(name="Description", value=self.description)
        embed.add_field(name="Start", value=self.start, inline=False)
        embed.add_field(name="End", value=self.end)
        embed.add_field(name="Registration Start", value=self.registration_start)
        embed.add_field(name="Registration End", value=self.registration_end)

        if registrations:
            value = ''
            for registration in self.registrations:
                value += f'{registration.discorduser.get_display_name(dc_client, self.guild_id)}\n'
            if value:
                embed.add_field(name="Registrations", value=value, inline=False)
            self._archive.registrations = value
            db.session.commit()

        return embed

    def get_summary_embed(self, dc_client: discord.Client):
        embed = discord.Embed(title=f'Summary')

        description = ''

        if len(self.registrations) == 0:
            return embed

        now = datetime.now()
        gains = utils.calc_gains(self.registrations, event=self, search=self.start)

        def key(x: Gain):
            if x.client.rekt_on:
                # Trick to make the sort rank the first rekt last
                return -(now - x.client.rekt_on).total_seconds() * 100
            else:
                return x.relative

        gains.sort(key=key, reverse=True)

        description += f'**Best Trader :crown:**\n' \
                       f'{gains[0].client.discorduser.get_display_name(dc_client, self.guild_id)}\n'

        description += f'\n**Worst Trader :disappointed_relieved:**\n' \
                       f'{gains[len(gains) - 1].client.discorduser.get_display_name(dc_client, self.guild_id)}\n'

        initials = [client.initial for client in self.registrations]
        initials.sort(key=lambda x: x.amount, reverse=True)

        description += f'\n**Highest Stakes :moneybag:**\n' \
                       f'{initials[0].client.discorduser.get_display_name(dc_client, self.guild_id)}\n'

        description += f'\n**Lowest Stakes :yawning_face:**\n' \
                       f'{initials[len(initials) - 1].client.discorduser.get_display_name(dc_client, self.guild_id)}\n'

        def calc_volatility(client: Client):
            if len(client.history) == 0:
                return 0.0

            result, prev_diff = 0.0, 0.0
            init_amount = client.initial.amount
            for balance in client.history:
                sqr_diff = (balance.amount - init_amount)**2
                result += sqr_diff - prev_diff
                if balance.amount == 0.0:
                    break
                prev_diff = sqr_diff

            return result / init_amount**2

        volatility = [
            (
                client,
                calc_volatility(client)
            )
            for client in self.registrations
        ]

        volatility.sort(key=lambda x: x[1], reverse=True)

        description += f'\n**Most Degen Trader :grimacing:**\n' \
                       f'{volatility[0][0].discorduser.get_display_name(dc_client, self.guild_id)}\n'

        description += f'\n**Still HODLing :sleeping:**\n' \
                       f'{volatility[len(volatility) - 1][0].discorduser.get_display_name(dc_client, self.guild_id)}\n'

        cum_percent = 0.0
        cum_dollar = 0.0
        for gain in gains:
            cum_percent += gain.relative if gain.relative else 0
            cum_dollar += gain.absolute if gain.absolute else 0

        cum_percent /= len(gains) or 1  # Avoid division by zero

        description += f'\nLast but not least... ' \
                       f'\nIn total you {"made" if cum_dollar >= 0.0 else "lost"} {abs(round(cum_dollar, ndigits=2))}$' \
                       f'\nCumulative % performance: {round(cum_percent, ndigits=2)}%'

        description += '\n'
        embed.description = description
        self._archive.summary = description

        return embed

    async def create_complete_history(self, dc_client: discord.Client):

        path = f'HISTORY_{self.guild_id}_{self.channel_id}_{int(self.start.timestamp())}.png'
        await utils.create_history(
            custom_title=f'Complete history for {self.name}',
            to_graph=[
                (client, client.discorduser.get_display_name(dc_client, self.guild_id))
                for client in self.registrations
            ],
            event=self,
            start=self.start,
            end=self.end,
            currency_display='%',
            currency='$',
            percentage=True,
            path=DATA_PATH + path,
            throw_exceptions=False
        )

        file = discord.File(DATA_PATH + path, path)
        self._archive.history_path = path
        db.session.commit()

        return file

    async def create_leaderboard(self, dc_client: discord.Client, mode='gain', time: datetime = None) -> discord.Embed:
        leaderboard = await utils.create_leaderboard(dc_client, self.guild_id, mode, time=time, event=self)
        self._archive.leaderboard = leaderboard.description

        return leaderboard

    @property
    def _archive(self):
        if not self.archive:
            self.archive = Archive(event_id=self.id)
            db.session.add(self.archive)
        return self.archive

    def __hash__(self):
        return self.id.__hash__()
