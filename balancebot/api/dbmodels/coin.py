from datetime import datetime
from typing import List, Deque, Optional
from dataclasses import dataclass
from balancebot.api.database import *


class OI(Base):
    id = Column(Integer, nullable=False, primary_key=True)
    time: Column(DateTime, nullable=False)
    value: Column(Float, nullable=False)


class Volume(Base):
    id = Column(Integer, nullable=False, primary_key=True)
    time: Column(DateTime, nullable=False)
    spot: Column(Float, nullable=False)
    perp: Column(Float, nullable=False)
    ratio_data: Optional[List[float]]
    avg_ratio: Optional[float]


@dataclass
class VolumeHistory:
    spot_data: Optional[Deque[float]]
    perp_data: Optional[Deque[float]]
    ratio_data: Optional[List[float]]
    avg_ratio: Optional[float]


@dataclass
class Coin:
    coin_name: str
    spot_ticker: str
    perp_ticker: str

    # Volume Data
    volume_history: VolumeHistory

    # OI Data
    open_interest_data: Optional[Deque[OI]]
