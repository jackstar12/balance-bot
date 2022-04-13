from datetime import datetime
from typing import Optional, Dict

from pydantic import BaseModel


class WebsocketMessage(BaseModel):
    type: str
    channel: Optional[str]
    data: Optional[Dict]


class WebsocketConfig(BaseModel):
    id: Optional[int]
    since: Optional[datetime]
    to: Optional[datetime]
    currency: Optional[str]
