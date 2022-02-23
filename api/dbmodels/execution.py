from api.database import db
from api.dbmodels.serializer import Serializer


class Execution(db.Model, Serializer):
    __tablename__ = 'execution'
    id = db.Column(db.Integer, primary_key=True)
    trade_id = db.Column(db.Integer, db.ForeignKey('trade.id', ondelete='CASCADE'), nullable=True)

    symbol = db.Column(db.String, nullable=False)
    price = db.Column(db.Float, nullable=False)
    qty = db.Column(db.Float, nullable=False)
    side = db.Column(db.String, nullable=False)
    time = db.Column(db.DateTime, nullable=False)
    type = db.Column(db.String, nullable=True)



