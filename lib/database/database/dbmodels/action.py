from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property

from database.dbmodels.mixins.editsmixin import EditsMixin

from database.dbsync import Base


class ActionType(Enum):
    WEBHOOK = "webhook"
    DISCORD = "discord"


class Action(Base, EditsMixin):
    __tablename__ = 'action'

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)

    namespace = sa.Column(sa.String(length=12), nullable=False)
    topic = sa.Column(sa.String, nullable=False)
    trigger_ids = sa.Column(JSONB, nullable=False)

    action_type = sa.Column(sa.Enum(ActionType), nullable=False)
    extra = sa.Column(JSONB, nullable=False)

    @hybrid_property
    def all_ids(self):
        return {
            'user_id': self.user_id,
            **self.trigger_ids
        }
