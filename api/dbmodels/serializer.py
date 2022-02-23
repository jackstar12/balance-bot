from sqlalchemy.inspection import inspect
from api.database import db


class Serializer:

    def is_data(self):
        return False

    # The full flag is needed to avoid cyclic serializations
    def serialize(self, data=True, full=True):
        if data or not self.is_data():
            s = {}
            for k in inspect(self).attrs.keys():
                v = getattr(self, k)
                if issubclass(type(v), list):
                    if data or full:
                        v = Serializer.serialize_list(v, data=data, full=False)
                    else:
                        continue
                elif issubclass(type(v), Serializer):
                    if full:
                        v = v.serialize(full=False, data=data)
                    else:
                        continue
                s[k] = v
            return s

    @staticmethod
    def serialize_list(l, data=True, full=True):
        r = []
        for m in l:
            s = m.serialize(data, full)
            if s:
                r.append(s)
        return r
