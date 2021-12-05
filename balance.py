from dataclasses import dataclass


@dataclass
class Balance:
    amount: float
    currency: str
    error: str

