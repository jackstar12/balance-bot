from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import pytz
from pydantic import Field
from sqlalchemy import Column, select
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.common.models import BaseModel
from tradealpha.common.dbasync import db_all

if TYPE_CHECKING:
    from tradealpha.common.dbmodels.user import User


class QueryParams(BaseModel):
    client_ids: set[int]
    currency: str
    since: Optional[datetime] = Field(default_factory=lambda: datetime.fromtimestamp(0, pytz.utc))
    to: Optional[datetime]
    limit: Optional[int]

    def within(self, other: QueryParams):
        return (
                (not other.since or (self.since and self.since >= other.since))
                and
                (not other.to or (self.to and self.to < other.to))
        )


class QueryMixin:
    time_col: Column

    @classmethod
    async def query(cls,
                    *eager,
                    time_col: Column,
                    user: User,
                    ids: list[int],
                    params: QueryParams,
                    db: AsyncSession) -> list:
        from tradealpha.common import dbutils
        return await db_all(
            dbutils.add_client_filters(
                select(cls).filter(
                    cls.id.in_(ids) if ids else True,
                    time_col >= params.since if params.since else True,
                    time_col <= params.to if params.to else True
                ).join(
                    cls.client
                ).limit(
                    params.limit
                ),
                user=user,
                client_ids=params.client_ids
            ),
            *eager,
            session=db
        )
