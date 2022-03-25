import utils
import numpy
from models.gain import Gain
from api.dbmodels.archive import Archive
from api.dbmodels.serializer import Serializer
from datetime import datetime
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
from config import DATA_PATH
import discord

from api.database import Base, session as session
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, ForeignKey, Text, String, DateTime, Float, PickleType, BigInteger, Table

association = Table('association',
                    Column('event_id', Integer, ForeignKey('event.id', ondelete="CASCADE"), primary_key=True),
                    Column('client_id', Integer, ForeignKey('client.id', ondelete="CASCADE"), primary_key=True)
                    )


class Event(Base, Serializer):
    __tablename__ = 'event'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    registration_start = Column(DateTime, nullable=False)
    registration_end = Column(DateTime, nullable=False)
    start = Column(DateTime, nullable=False)
    end = Column(DateTime, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)

    registrations = relationship('Client', secondary=association, backref='events')
    archive = relationship('Archive', backref='event', uselist=False, cascade="all, delete")

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
            session.commit()

        return embed

    def get_summary_embed(self, dc_client: discord.Client):
        embed = discord.Embed(title=f'Summary')

        description = ''

        if len(self.registrations) == 0:
            return embed

        now = datetime.now()
        gains = utils.calc_gains(self.registrations, self.guild_id, self.start, archived=now > self.end)

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

        gains.sort(key=lambda x: x.absolute, reverse=True)

        description += f'\n**Highest Stakes :moneybag:**\n' \
                       f'{gains[0].client.discorduser.get_display_name(dc_client, self.guild_id)}\n'

        def non_null_balances(history):
            balances = []
            for balance in history:
                balances.append(balance.amount)
                if balance.amount == 0.0:
                    break
            return balances

        volatility = [
            (
                client,
                numpy.array(
                    non_null_balances(client.history)
                ).std() / client.history[0].amount
            )
            for client in self.registrations
        ]
        volatility.sort(key=lambda x: x[1], reverse=True)

        description += f'\n**Most Degen Trader :grimacing:**\n' \
                       f'{volatility[0].client.discorduser.get_display_name(dc_client, self.guild_id)}\n'

        description += f'\n**Still HODLing :sleeping:**\n' \
                       f'{volatility[len(volatility) - 1].client.discorduser.get_display_name(dc_client, self.guild_id)}\n'

        cum_percent = 0.0
        cum_dollar = 0.0
        for gain in gains:
            cum_percent += gain[1][0]
            cum_dollar += gain[1][1]

        cum_percent /= len(gains) or 1  # Avoid division by zero

        description += f'\nLast but not least... ' \
                       f'\nIn total you {"made" if cum_dollar >= 0.0 else "lost"} {round(cum_dollar, ndigits=2)}$' \
                       f'\nCumulative % performance: {round(cum_percent, ndigits=2)}%'

        description += '\n'
        embed.description = description

        return embed

    async def create_complete_history(self, dc_client: discord.Client):

        path = f'HISTORY_{self.guild_id}_{self.channel_id}_{int(self.start.timestamp())}.png'
        await utils.create_history(
            custom_title=f'Complete history for {self.name}',
            to_graph=[
                (client, client.discorduser.get_display_name(dc_client, self.guild_id))
                for client in self.registrations
            ],
            guild_id=self.guild_id,
            start=self.start,
            end=self.end,
            currency_display='%',
            currency='$',
            percentage=True,
            path=DATA_PATH + path,
            archived=self.end < datetime.now()
        )

        file = discord.File(DATA_PATH + path, path)
        self._archive.history_path = path
        session.commit()

        return file

    async def create_leaderboard(self, dc_client: discord.Client, mode='gain', time: datetime = None) -> discord.Embed:
        leaderboard = await utils.create_leaderboard(dc_client, self.guild_id, mode, time)
        self._archive.leaderboard = leaderboard.description

        return leaderboard

    @property
    def _archive(self):
        if not self.archive:
            self.archive = Archive(event_id=self.id)
            session.add(self.archive)
        return self.archive

    def __hash__(self):
        return self.id.__hash__()
