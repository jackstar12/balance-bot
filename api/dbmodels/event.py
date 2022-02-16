import utils
import numpy
from api.database import db
from api.dbmodels.serializer import Serializer
from datetime import datetime
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
from config import DATA_PATH
import discord

association = db.Table('association',
                       db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True),
                       db.Column('client_id', db.Integer, db.ForeignKey('client.id'), primary_key=True)
                       )


class Event(db.Model, Serializer):
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

    @hybrid_property
    def is_active(self):
        return self.start <= datetime.now() <= self.end

    @hybrid_property
    def is_free_for_registration(self):
        return self.registration_start <= datetime.now() <= self.registration_end

    def get_discord_embed(self, registrations=False):
        embed = discord.Embed(title=f'Event')
        embed.add_field(name="Name", value=self.name)
        embed.add_field(name="Description", value=self.description, inline=False)
        embed.add_field(name="Start", value=self.start)
        embed.add_field(name="End", value=self.end, inline=False)
        embed.add_field(name="Registration Start", value=self.registration_start)
        embed.add_field(name="Registration End", value=self.registration_end, inline=False)

        if registrations:
            value = ''
            for registration in self.registrations:
                value += f'{registration.discorduser.name}\n'
            if value:
                embed.add_field(name="Registrations", value=value, inline=False)

        return embed

    def get_summary_embed(self):
        embed = discord.Embed(title=f'Summary')

        awards = discord.Embed(title=f'Awards')
        description = ''

        gains = utils.calc_gains(self.registrations, self.guild_id, self.start)
        gains.sort(key=lambda x: x[1][0], reverse=True)

        description += f'**Best Trader :crown:**\n' \
                       f'{gains[0][0].discorduser.name}\n'

        description += f'\n**Worst Trader :disappointed_relieved:**\n' \
                       f'{gains[len(gains) - 1][0].discorduser.name}\n'

        gains.sort(key=lambda x: x[1][1], reverse=True)

        description += f'\n**Highest Stakes:**\n' \
                       f'{gains[0][0].discorduser.name}\n'

        # trade_counts = [len(client.trades) for client in self.registrations]
        # trade_counts.sort()

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

        description += f'**Most Degen Trader :grimacing:**\n' \
                       f'{volatility[0][0].discorduser.name}\n'

        description += f'\n**Still HODLing:sleeping:**\n' \
                       f'{volatility[len(volatility) - 1][0].discorduser.name}\n'

        description += '\n'
        embed.description = description

        return embed

    def create_complete_history(self):
        utils.create_history(
            custom_title=f'Complete history for {self.name}',
            to_graph=[(client, client.id) for client in self.registrations],
            guild_id=self.guild_id,
            start=self.start,
            end=self.end,
            currency_display='%',
            currency='$',
            percentage=True,
            path=DATA_PATH + "tmp.png"
        )

        file = discord.File(DATA_PATH + "tmp.png", "history.png")
        return file
