from dataclasses import dataclass


@dataclass
class Balance:
    amount: float
    currency: str
    error: str

    def to_json(self, currency=False):
        json = {
            'amount': self.amount,
        }
        if self.error:
            json['error'] = self.error
        if currency:
            json['currency'] = self.currency
        return json

