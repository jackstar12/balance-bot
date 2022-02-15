from api.database import db
from api.dbmodels.serializer import Serializer


class User(db.Model, Serializer):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, unique=True, nullable=False)
    password = db.Column(db.String, unique=True, nullable=False)
    salt = db.Column(db.String, nullable=False)
    clients = db.relationship('Client', backref='user', lazy=True)
    discord_user_id = db.Column(db.Integer(), db.ForeignKey('discorduser.id'), nullable=True)

    def serialize(self, data=False, full=True):
        s = super().serialize(data, full)
        del s['password']
        del s['salt']
        return s
