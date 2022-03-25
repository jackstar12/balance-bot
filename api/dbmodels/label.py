from api.database import Base, session as session
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, ForeignKey, Text, String, DateTime, Float, PickleType, BigInteger, Table
from api.dbmodels.serializer import Serializer


class Label(Base, Serializer):
    id: int = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    name: str = Column(String, nullable=False)
    color: str = Column(String, nullable=False)

    def serialize(self, full=True, data=True, *args, **kwargs):
        if data:
            return self.id
        else:
            return super().serialize(full, data, *args, **kwargs)


