from datetime import datetime

import pytz
import sqlalchemy as sa
from sqlalchemy import func


def now():
    return datetime.now(pytz.utc)


class EditsMixin:
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=func.now(), default=now)
    last_edited = sa.Column(sa.DateTime(timezone=True), onupdate=now)
