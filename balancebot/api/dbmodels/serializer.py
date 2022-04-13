from datetime import datetime

from sqlalchemy.inspection import inspect
from sqlalchemy.orm.dynamic import AppenderQuery


class Serializer:
    __serializer_anti_recursion__ = False
    __serializer_forbidden__ = []

    def is_data(self):
        return False

    # The full flag is needed to avoid cyclic serializations
    def serialize(self, full=False, data=True, *args, **kwargs):
        if not self.__class__.__serializer_anti_recursion__:
            self.__class__.__serializer_anti_recursion__ = True
            try:
                s = None
                if data or not self.is_data():
                    s = {}
                    for k in inspect(self).attrs.keys():
                        if k not in self.__serializer_forbidden__:
                            v = getattr(self, k)
                            if issubclass(type(v), list):
                                v = Serializer.serialize_list(v, data=data, full=full, *args, **kwargs)
                            elif isinstance(v, AppenderQuery):
                                if data:
                                    v = v.all()
                                else:
                                    v = []
                            elif isinstance(v, datetime):
                                v = v.timestamp()
                            elif issubclass(type(v), Serializer):
                                if full:
                                    v = v.serialize(full=full, data=data, *args, **kwargs)
                                else:
                                    continue
                            s[k] = v
                self.__class__.__serializer_anti_recursion__ = False
                return s
            except Exception as e:
                self.__class__.__serializer_anti_recursion__ = False
                raise e

    @staticmethod
    def serialize_list(l, data=True, full=False, *args, **kwargs):
        r = []
        for m in l:
            s = m.serialize(full, data, *args, **kwargs)
            if s:
                r.append(s)
        return r
