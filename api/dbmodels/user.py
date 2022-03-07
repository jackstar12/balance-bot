from api.database import db
from api.dbmodels.serializer import Serializer


class User(db.Model, Serializer):
    __tablename__ = 'user'
    __serializer_forbidden__ = ['password', 'salt']

    # Identity
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, unique=True, nullable=False)
    password = db.Column(db.String, unique=True, nullable=False)
    salt = db.Column(db.String, nullable=False)
    discord_user_id = db.Column(db.Integer(), db.ForeignKey('discorduser.id', ondelete='SET NULL'), nullable=True)

    # Data
    clients = db.relationship('Client', backref='user', lazy=True)
    labels = db.relationship('Label', backref='client', lazy=True, cascade="all, delete")


