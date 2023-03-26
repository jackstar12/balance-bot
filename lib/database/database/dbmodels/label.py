from typing import Any

from sqlalchemy import Integer, ForeignKey, String
from sqlalchemy.orm import relationship, declared_attr

from database.dbmodels.mixins.serializer import Serializer
from database.dbsync import Base, BaseMixin


class Group:
    id = mapped_column(Integer, primary_key=True)
    name: Mapped[str]

    @declared_attr
    def user_id(self):
        return Column(ForeignKey('user.id', ondelete="CASCADE"), nullable=False)


class LabelGroup(Group, Base, Serializer, BaseMixin):
    __tablename__ = 'labelgroup'
    labels = relationship('Label',
                          back_populates='group',
                          passive_deletes=True,
                          cascade="all, delete")


class Label(Base, Serializer, BaseMixin):
    __tablename__ = 'label'
    id: Any = mapped_column(Integer, primary_key=True)
    group_id = mapped_column(ForeignKey(LabelGroup.id, ondelete="CASCADE"), nullable=False)

    name: Mapped[str]
    color: Mapped[str]

    group = relationship(LabelGroup,
                         lazy='raise',
                         foreign_keys=group_id,)

    def serialize(self, full=True, data=True, *args, **kwargs):
        if data:
            return self.id
        else:
            return super().serialize(full, data, *args, **kwargs)
