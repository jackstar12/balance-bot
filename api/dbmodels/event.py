from api.database import db


class Event(db.Model):
    __tablename__ = 'event'
    id = db.Column(db.Integer, primary_key=True)
    registration_start = db.Column(db.DateTime, nullable=False)
    registration_end = db.Column(db.DateTime, nullable=False)
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)
    name = db.Column(db.String, nullable=False)
    description = db.Column(db.String, nullable=False)
    #registrations = db.relationship('DiscordUser', backref='event', lazy=True)
