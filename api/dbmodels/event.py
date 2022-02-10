from api.database import db
from datetime import datetime
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
import discord

association = db.Table('association',
                       db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True),
                       db.Column('client_id', db.Integer, db.ForeignKey('client.id'), primary_key=True)
                       )


class Event(db.Model):
    __tablename__ = 'event'
    id = db.Column(db.Integer, primary_key=True)
    guild_id = db.Column(db.Integer, nullable=False)
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

    def get_discord_embed(self):
        embed = discord.Embed(title=f'Event **{self.name}**')
        embed.add_field(name="Start", value=self.start)
        embed.add_field(name="End", value=self.end)
        embed.add_field(name="Registration Start", value=self.registration_start)
        embed.add_field(name="Registration End", value=self.registration_end)

        return embed


