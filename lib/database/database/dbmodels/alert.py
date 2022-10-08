import discord
from sqlalchemy import Column, Integer, ForeignKey, String, Enum, Numeric
from sqlalchemy.dialects.postgresql import UUID

from database.dbmodels.mixins.serializer import Serializer
from database.dbsync import Base
from database.enums import Side


class Alert(Base, Serializer):
    __tablename__ = "alert"
    __serializer_data_forbidden__ = ["user", "discord_user"]

    id: int = Column(Integer, primary_key=True)
    user_id: UUID = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    discord_user_id: int = Column(ForeignKey('oauth_account.account_id', ondelete='SET NULL'), nullable=True)

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
