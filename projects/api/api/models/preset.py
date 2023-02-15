from datetime import datetime
from decimal import Decimal

from database.models import BaseModel, OrmBaseModel, OutputID


class PresetInfo(OrmBaseModel):
    id: OutputID
    name: str
    type: str
    attrs: dict


class PresetCreate(OrmBaseModel):
    name: str
    type: str
