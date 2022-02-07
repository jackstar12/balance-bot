from dataclasses import dataclass
from datetime import datetime
from typing import List

from models.discorduser import DiscordUser


@dataclass
class Event:
    registration_start: datetime
    registration_end: datetime
    start: datetime
    end: datetime
    name: str
    registrations: List[DiscordUser] = None
    description: str = None
