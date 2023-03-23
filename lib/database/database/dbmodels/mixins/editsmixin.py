from datetime import datetime

import pytz
import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import mapped_column, Mapped


def now():
    return datetime.now(pytz.utc)


class EditsMixin:
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=func.now(), default=now)
    last_edited: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), onupdate=now)
