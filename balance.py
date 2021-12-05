from dataclasses import dataclass


@dataclass
class Balance:
    amount: float
    currency: str
    error: str

    def to_json(self):
        json = {
            'amount': self.amount,
            'currency': self.currency
        }
        if self.error:
            json['error'] = self.error
        return json

