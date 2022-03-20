from datetime import datetime

from api.database import db
import config


class Balance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id', ondelete="CASCADE"), nullable=True)
    time = db.Column(db.DateTime, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String, nullable=False)
    error = db.Column(db.String, nullable=True)
    extra_currencies = db.Column(db.PickleType, nullable=True)

    def to_json(self, currency=False):
        json = {
            'amount': self.amount,
        }
        if self.error:
            json['error'] = self.error
        if currency or self.currency != '$':
            json['currency'] = self.currency
        if self.extra_currencies:
            json['extra_currencies'] = self.extra_currencies
        return json

    def to_string(self, display_extras=True):
        string = f'{round(self.amount, ndigits=config.CURRENCY_PRECISION.get(self.currency, 3))}{self.currency}'

        if self.extra_currencies and display_extras:
            first = True
            for currency in self.extra_currencies:
                string += f'{" (" if first else "/"}{round(self.extra_currencies[currency], ndigits=config.CURRENCY_PRECISION.get(currency, 3))}{currency}'
                first = False
            if not first:
                string += ')'

        return string


def balance_from_json(data: dict, time: datetime):
    currency = data.get('currency', '$')
    return Balance(
        amount=round(data.get('amount', 0), ndigits=config.CURRENCY_PRECISION.get(currency, 3)),
        currency=currency,
        extra_currencies=data.get('extra_currencies', None),
        time=time
    )
