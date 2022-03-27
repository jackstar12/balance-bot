from balancebot.api.database import Base
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType
from balancebot.api.dbmodels.serializer import Serializer


class Label(Base, Serializer):
    __tablename__ = 'label'
    id: int = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    name: str = Column(String, nullable=False)
    color: str = Column(String, nullable=False)

    def serialize(self, full=True, data=True, *args, **kwargs):
        if data:
            return self.id
        else:
            return super().serialize(full, data, *args, **kwargs)


