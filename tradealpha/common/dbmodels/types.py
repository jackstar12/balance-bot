from __future__ import annotations
from abc import ABC
from typing import Optional
import sqlalchemy as sa
from pydantic import BaseModel, Extra
from sqlalchemy import orm, TypeDecorator
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
import tradealpha.common.utils as utils
from tradealpha.common.dbsync import Base
from tradealpha.common.models.gain import Gain


#class DataModel(BaseModel):
class DocumentModel(BaseModel):
    type: str
    content: 'DocumentModel' = None

    class Config:
        extra = Extra.allow


class Document(TypeDecorator):

    impl = JSONB

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value


class Data(TypeDecorator):

    impl = JSONB

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value
