from __future__ import annotations


from sqlalchemy import TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB

from database.models.document import DocumentModel
from database.models.platform import PlatformModel

Document = DocumentModel.get_sa_type(exclude_none=True, validate=True)
Platform = PlatformModel.get_sa_type()


class Data(TypeDecorator):
    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value
