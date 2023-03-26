from typing import Optional

import discord
from sqlalchemy import Integer, ForeignKey, String, Enum, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, Mapped

from database.dbmodels.mixins.serializer import Serializer
from database.dbsync import Base, BaseMixin, intpk
from database.enums import Side


class Alert(Base, Serializer, BaseMixin):
    __tablename__ = "alert"
    __serializer_data_forbidden__ = ["user", "discord_user"]

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    discord_user_id: Mapped[int] = mapped_column(ForeignKey('oauth_account.account_id', ondelete='SET NULL'), nullable=True)

    symbol: Mapped[str]
    price: Mapped[float] = mapped_column(Numeric, nullable=False)
    exchange: Mapped[str]
    side: Mapped[Side] = mapped_column(Enum(Side), nullable=True)
    note: Mapped[Optional[str]]

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
