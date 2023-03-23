import sqlalchemy as sa
from sqlalchemy import orm

from database.dbmodels.mixins.editsmixin import EditsMixin
from database.dbsync import Base


class Preset(Base, EditsMixin):
    __tablename__ = 'preset'

    id = mapped_column(sa.Integer, primary_key=True)
    user_id = mapped_column(sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    name = mapped_column(sa.String, nullable=False)
    type = mapped_column(sa.String, nullable=False)
    attrs = mapped_column(sa.JSON, nullable=False)

    user = orm.relationship('User')
