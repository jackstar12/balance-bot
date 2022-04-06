from datetime import datetime

import discord
import pytz
from discord.ext.commands import Bot
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.api.database import Base
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType

from balancebot.bot import config
from balancebot.api.dbmodels.serializer import Serializer


class Alert(Base):
    __tablename__ = "alert"

    id: int = Column(Integer, primary_key=True)
    user_id: int = Column(Integer, ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    discord_user_id: int = Column(Integer, ForeignKey('discord_user.id', ondelete='SET NULL'), nullable=True)

    symbol: str = Column(String, nullable=False)
    price: float = Column(Float, nullable=False)
    note: str = Column(String, nullable=True)

    def get_discord_embed(self):
        embed = discord.Embed(
            title="Alert"
        ).add_field(
            name='Symbol', value=self.symbol
        ).add_field(
            name='Price', value=self.price
        )
        if self.note:
            embed.add_field(name='Note', value=self.note)

        return embed
