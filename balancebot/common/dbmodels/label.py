from fastapi_users_db_sqlalchemy import GUID

from balancebot.common.dbsync import Base
from sqlalchemy import Column, Integer, ForeignKey, String
from balancebot.common.dbmodels.serializer import Serializer


class Label(Base, Serializer):
    __tablename__ = 'label'
    id: int = Column(Integer, primary_key=True)
    user_id = Column(GUID, ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    name: str = Column(String, nullable=False)
    color: str = Column(String, nullable=False)

    async def serialize(self, full=True, data=True, *args, **kwargs):
        if data:
            return self.id
        else:
            return await super().serialize(full, data, *args, **kwargs)


