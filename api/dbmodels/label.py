from api.database import db
from api.dbmodels.serializer import Serializer


class Label(db.Model, Serializer):
    id: int = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    name: str = db.Column(db.String, nullable=False)
    color: str = db.Column(db.String, nullable=False)

