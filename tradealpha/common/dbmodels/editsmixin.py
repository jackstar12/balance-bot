import sqlalchemy as sa
import tradealpha.common.utils as utils


class EditsMixin:
    created_at = sa.Column(sa.DateTime(timezone=True), default=utils.now)
    last_edited = sa.Column(sa.DateTime(timezone=True), onupdate=utils.now)