from api.database import Base
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, ForeignKey, Text, String


class Archive(Base):

    __tablename__ = 'archive'

    event_id = Column(Integer, ForeignKey('event.id'), nullable=False, primary_key=True)
    registrations = Column(Text, nullable=True)
    leaderboard = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    history_path = Column(String, nullable=True)
