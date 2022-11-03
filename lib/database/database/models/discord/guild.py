from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from database.enums import Tier
from database.models import BaseModel, OutputID, InputID, OrmBaseModel

if TYPE_CHECKING:
    from database.dbmodels import GuildAssociation as GuildAssociationDB
    from database.dbmodels.discord.guild import Guild as GuildDB


class GuildAssociation(OrmBaseModel):
    client_id: Optional[OutputID]
    guild_id: str


class TextChannel(OrmBaseModel):
    id: OutputID
    name: str
    category: str


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

    @classmethod
    def from_member(cls, guild: discord.Guild, member_id: int):
        member = guild.get_member(member_id)
        if member:
            return GuildData(
                id=guild.id,
                name=guild.name,
                icon_url=str(guild.icon_url),
                text_channels=[
                    TextChannel(
                        id=tc.id,
                        name=tc.name,
                        category=tc.category.name
                    )
                    for tc in guild.text_channels if tc.permissions_for(member).read_messages
                ],
                is_admin=member.guild_permissions.administrator
            )


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
