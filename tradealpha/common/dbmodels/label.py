from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy.orm import relationship, backref, declared_attr

from tradealpha.common.dbsync import Base
from sqlalchemy import Column, Integer, ForeignKey, String
from tradealpha.common.dbmodels.mixins.serializer import Serializer


class Group:
    id = Column(Integer, primary_key=True)
    name: str = Column(String, nullable=False)

    @declared_attr
    def user_id(self):
        return Column(ForeignKey('user.id', ondelete="CASCADE"), nullable=False)


class LabelGroup(Group, Base, Serializer):
    __tablename__ = 'labelgroup'
    labels = relationship('Label', back_populates='group', lazy='raise')


class Label(Base, Serializer):
    __tablename__ = 'label'
    id = Column(Integer, primary_key=True)
    group_id = Column(ForeignKey(LabelGroup.id, ondelete="CASCADE"), nullable=False)

    name: str = Column(String, nullable=False)
    color: str = Column(String, nullable=False)

    group = relationship(LabelGroup,
                         lazy='raise',
                         foreign_keys=group_id,)

    def serialize(self, full=True, data=True, *args, **kwargs):
        if data:
            return self.id
        else:
            return super().serialize(full, data, *args, **kwargs)
