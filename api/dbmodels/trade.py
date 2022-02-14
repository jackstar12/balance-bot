from api.database import db
from api.dbmodels.serializer import Serializer


class Trade(db.Model, Serializer):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=True)

    symbol = db.Column(db.String, nullable=False)
    price = db.Column(db.Float, nullable=False)
    qty = db.Column(db.Float, nullable=False)
    side = db.Column(db.String, nullable=False)
    type = db.Column(db.String, nullable=False)
    label = db.Column(db.String, nullable=True)
    memo = db.Column(db.String, nullable=True)

    time = db.Column(db.DateTime, nullable=False)

