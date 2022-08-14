from datetime import datetime
from enum import Enum
from typing import Optional

from fastapi.encoders import jsonable_encoder
from pydantic.main import BaseModel
from sqlalchemy import select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import InstrumentedAttribute, selectinload, RelationshipProperty
from sqlalchemy.orm.dynamic import AppenderQuery
from sqlalchemy.sql import Select

from tradealpha.common.dbasync import db_all


class Serializer:
    __serializer_anti_recursion__ = False
    __serializer_forbidden__ = []
    __serializer_data_forbidden__ = []

    @classmethod
    def is_data(cls):
        return False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # The full flag is needed to avoid cyclic serializations
    def serialize(self, full=False, data=True, include_none=True, *args, **kwargs):
        if not self.__class__.__serializer_anti_recursion__:
            self.__class__.__serializer_anti_recursion__ = True
            try:
                s = None
                if data or not self.is_data():
                    s = {}
                    for k in inspect(self).attrs.keys():
                        forbidden = self.__serializer_data_forbidden__ if data else self.__serializer_forbidden__
                        if k not in forbidden:
                            v = getattr(self, k)
                            if v is None:
                                continue
                            if issubclass(type(v), list):
                                v = Serializer.serialize_list(v, data=data, full=full, *args, **kwargs)
                            elif isinstance(v, AppenderQuery):
                                if data and None:
                                    v = []
                                    #v = await db_all(v.statement)
                                    #v = v.all()
                                else:
                                    v = []
                            elif isinstance(v, datetime):
                                v = v.timestamp()
                            elif issubclass(type(v), Enum):
                                v = v.value
                            elif issubclass(type(v), Serializer):
                                if full:
                                    v = v.serialize(full=full, data=data, include_none=include_none, *args, **kwargs)
                                else:
                                    continue
                            s[k] = v
                self.__class__.__serializer_anti_recursion__ = False
                return s
            except Exception as e:
                self.__class__.__serializer_anti_recursion__ = False
                raise e

    @staticmethod
    def serialize_list(l, data=True, full=False, include_none=True, *args, **kwargs):
        r = []
        for m in l:
            s = m.serialize(full, data, *args, include_none=include_none, **kwargs)
            if s:
                r.append(s)
        return r
