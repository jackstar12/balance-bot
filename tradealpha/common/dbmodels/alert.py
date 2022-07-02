import discord
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy.dialects.postgresql import UUID

from tradealpha.common.dbsync import Base
from sqlalchemy import Column, Integer, ForeignKey, String, BigInteger, Enum, Numeric

from tradealpha.common.dbmodels.serializer import Serializer
from tradealpha.common.enums import Side


class Alert(Base, Serializer):
    __tablename__ = "alert"
    __serializer_data_forbidden__ = ["user", "discord_user"]

    id: int = Column(Integer, primary_key=True)
    user_id: UUID = Column(GUID, ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    discord_user_id: int = Column(BigInteger, ForeignKey('discorduser.id', ondelete='SET NULL'), nullable=True)

    symbol: str = Column(String, nullable=False)
    price: float = Column(Numeric, nullable=False)
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
        ).add_field(
            name='Exchange', value=self.exchange
        )
        if self.note:
            embed.add_field(name='Note', value=self.note)

        return embed
