from sqlalchemy.inspection import inspect
from api.database import db


class Serializer:
    __serializer_anti_recursion__ = False

    __serializer_forbidden__ = []

    def is_data(self):
        return False

    # The full flag is needed to avoid cyclic serializations
    def serialize(self, data=True, full=True, *args, **kwargs):
        if not self.__serializer_anti_recursion__:
            self.__serializer_anti_recursion__ = True
            if data or not self.is_data():
                s = {}
                for k in inspect(self).attrs.keys():
                    if k not in self.__serializer_forbidden__:
                        v = getattr(self, k)
                        if issubclass(type(v), list):
                            v = Serializer.serialize_list(v, data=data, full=False, *args, **kwargs)
                        elif issubclass(type(v), Serializer):
                            if full:
                                v = v.serialize(full=False, data=data, *args, **kwargs)
                            else:
                                continue
                        s[k] = v
                return s
            self.__serializer_anti_recursion__ = False

    @staticmethod
    def serialize_list(l, data=True, full=True, *args, **kwargs):
        r = []
        for m in l:
            s = m.serialize(data, full, *args, **kwargs)
            if s:
                r.append(s)
        return r
