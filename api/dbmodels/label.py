from api.database import db
from api.dbmodels.serializer import Serializer


class Label(db.Model, Serializer):
    id: int = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name: str = db.Column(db.String, nullable=False)
    color: str = db.Column(db.String, nullable=False)

    def serialize(self, full=True, data=True, *args, **kwargs):
        if data:
            return self.id
        else:
            return super().serialize(full, data, *args, **kwargs)


