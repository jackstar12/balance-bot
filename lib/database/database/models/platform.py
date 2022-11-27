from typing import TypedDict, Literal, Any

from database.models import OrmBaseModel, OutputID


class PlatformModel(OrmBaseModel):
    name: str
    data: dict[str, Any]


class DiscordData(TypedDict):
    guild_id: OutputID
    channel_id: OutputID


class DiscordPlatform(PlatformModel):
    name: Literal['discord']
    data: DiscordData


class WebData(TypedDict):
    pass


class WebPlatform(PlatformModel):
    name: Literal['web']
    data: WebData
