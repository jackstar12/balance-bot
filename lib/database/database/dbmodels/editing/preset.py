import sqlalchemy as sa
from sqlalchemy import orm

from database.dbmodels.mixins.editsmixin import EditsMixin
from database.dbsync import Base


class Preset(Base, EditsMixin):
    __tablename__ = 'preset'

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    name = sa.Column(sa.String, nullable=False)
    type = sa.Column(sa.String, nullable=False)
    attrs = sa.Column(sa.JSON, nullable=False)

    user = orm.relationship('User')
