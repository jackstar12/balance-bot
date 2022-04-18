from balancebot.api.database import Base
from sqlalchemy import Column, Integer, ForeignKey, Text, String
from balancebot.api.dbmodels.serializer import Serializer


class Archive(Base, Serializer):

    __tablename__ = 'archive'

    event_id = Column(Integer, ForeignKey('event.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    registrations = Column(Text, nullable=True)
    leaderboard = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    history_path = Column(String, nullable=True)

    def is_data(self):
        return True
