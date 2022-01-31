from dataclasses import dataclass
from datetime import datetime
from typing import List

from Models.user import User


@dataclass
class Event:
    registration_start: datetime
    registration_end: datetime
    start: datetime
    end: datetime
    name: str
    registrations: List[User] = None
    description: str = None
