from datetime import datetime
from typing import Optional

from pydantic.main import BaseModel
from sqlalchemy import select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import joinedload, InstrumentedAttribute, selectinload, RelationshipProperty
from sqlalchemy.orm.dynamic import AppenderQuery
from sqlalchemy.sql import Select

from balancebot.api.database import Base
from balancebot.api.database_async import db_all


class Serializer:
    __serializer_anti_recursion__ = False
    __serializer_forbidden__ = []
    __serializer_data_forbidden__ = []

    @classmethod
    def is_data(cls):
        return False

    # The full flag is needed to avoid cyclic serializations
    async def serialize(self, model: Optional[BaseModel] = None, full=False, data=True, *args, **kwargs):
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
                            if issubclass(type(v), list):
                                v = await Serializer.serialize_list(v, data=data, full=full, *args, **kwargs)
                            elif isinstance(v, AppenderQuery):
                                if data:
                                    #v = await db_all(v.statement)
                                    v = v.all()
                                else:
                                    v = []
                            elif isinstance(v, datetime):
                                v = v.timestamp()
                            elif issubclass(type(v), Serializer):
                                if full:
                                    v = await v.serialize(full=full, data=data, *args, **kwargs)
                                else:
                                    continue
                            s[k] = v
                self.__class__.__serializer_anti_recursion__ = False
                return s
            except Exception as e:
                self.__class__.__serializer_anti_recursion__ = False
                raise e

    @classmethod
    def construct_load_options(cls, *, stmt: Select = None, option=None, full=False, data=True, **kwargs):
        if stmt is None:
            stmt = select(cls)

        options = []
        if not cls.__serializer_anti_recursion__:
            cls.__serializer_anti_recursion__ = True
            if data or not cls.is_data():
                try:
                    for k in inspect(cls).attrs.keys():
                        forbidden = cls.__serializer_data_forbidden__ if data else cls.__serializer_forbidden__
                        if k not in forbidden:
                            v = getattr(cls, k)
                            if isinstance(v, InstrumentedAttribute):
                                mapper = getattr(v.comparator, "mapper", None)
                                if mapper and isinstance(v.property, RelationshipProperty) and v.property.lazy != 'dynamic':
                                    if option is None:
                                        new_option = selectinload(v)
                                    else:
                                        new_option = option.selectinload(v)
                                    res_stmt = mapper.entity.construct_load_options(stmt=stmt, option=new_option, full=full, data=data, **kwargs)
                                    if res_stmt is not None:
                                        for path in new_option.path:
                                            print(str(path))
                                        print('\n')
                                        stmt = stmt.options(new_option)
                                        options.append(new_option)
                                    else:
                                        print('STOP!')
                    cls.__serializer_anti_recursion__ = False
                    return stmt
                except Exception as e:
                    cls.__serializer_anti_recursion__ = False
                    raise e
            cls.__serializer_anti_recursion__ = False


    @staticmethod
    async def serialize_list(l, data=True, full=False, *args, **kwargs):
        r = []
        for m in l:
            s = await m.serialize(full, data, *args, **kwargs)
            if s:
                r.append(s)
        return r
