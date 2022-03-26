from api.database import db


class Archive(db.Model):
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, primary_key=True)
    registrations = db.Column(db.Text, nullable=True)
    leaderboard = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    history_path = db.Column(db.String, nullable=True)
