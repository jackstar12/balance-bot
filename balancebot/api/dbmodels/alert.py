from datetime import datetime

import discord
import pytz
from discord.ext.commands import Bot
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.api.database import Base
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType, BigInteger, Enum

from balancebot.api.dbmodels.serializer import Serializer
from balancebot.common.enums import Side


class Alert(Base, Serializer):
    __tablename__ = "alert"
    __serializer_forbidden__ = ["side"]

    id: int = Column(Integer, primary_key=True)
    user_id: UUID = Column(GUID, ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    discord_user_id: int = Column(BigInteger, ForeignKey('discorduser.id', ondelete='SET NULL'), nullable=True)

    symbol: str = Column(String, nullable=False)
    price: float = Column(Float, nullable=False)
    exchange: str = Column(String, nullable=False)
    side: str = Column(Enum(Side), nullable=True)
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
