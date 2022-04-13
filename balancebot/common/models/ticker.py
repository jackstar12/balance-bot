from typing import NamedTuple


class Ticker(NamedTuple):

    symbol: str
    exchange: str
    price: float
    ts: int
