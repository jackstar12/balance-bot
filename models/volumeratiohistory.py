from typing import NamedTuple, List, Deque, Optional
from dataclasses import dataclass
from models.volumeratio import VolumeRatio


@dataclass
class VolumeRatioHistory:
    coin_name: str
    spot_name: str
    perp_name: str
    spot_data: Optional[Deque[float]]
    perp_data: Optional[Deque[float]]
    ratio_data: Optional[List[float]]
    avg_ratio: Optional[float]
