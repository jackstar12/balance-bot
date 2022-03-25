from typing import NamedTuple, List, Deque
from models.volumeratio import VolumeRatio

class VolumeRatioHistory(NamedTuple):
    spot_name: str
    spot_data: Deque[float]
    perp_name: str
    perp_data: Deque[float]
    ratio_data: List[float]
