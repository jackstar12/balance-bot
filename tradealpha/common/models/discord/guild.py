from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from tradealpha.common.enums import Tier
from tradealpha.common.models import BaseModel, OutputID, InputID, OrmBaseModel

if TYPE_CHECKING:
    from tradealpha.common.dbmodels import GuildAssociation as GuildAssociationDB
    from tradealpha.common.dbmodels.discord.guild import Guild as GuildDB


class GuildAssociation(OrmBaseModel):
    client_id: Optional[OutputID]
    guild_id: str


class TextChannel(OrmBaseModel):
    id: OutputID
    name: str


class UserRequest(BaseModel):
    user_id: InputID


class GuildRequest(UserRequest):
    guild_id: InputID


class MessageRequest(BaseModel):
    channel_id: InputID
    guild_id: InputID
    message: Optional[str]
    embed: Optional[dict]


class GuildData(OrmBaseModel):
    id: OutputID
    name: str
    icon_url: Optional[str]
    text_channels: list[TextChannel]
    is_admin: bool


class Guild(OrmBaseModel):
    data: GuildData
    events: list
    client_id: Optional[OutputID]
    # events: List[EventInfo]
    tier: Tier

    @classmethod
    def from_association(cls, data: GuildData, guild: GuildDB, association: GuildAssociationDB):
        return cls(
            data=data,
            tier=guild.tier,
            events=guild.events,
            client_id=association.client_id if association else None
        )
