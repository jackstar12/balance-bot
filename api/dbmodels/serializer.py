from sqlalchemy.inspection import inspect
from api.database import db


class Serializer:

    # The full flag is needed to avoid cyclic serializations
    def serialize(self, full=True):
        s = {}
        for k in inspect(self).attrs.keys():
            v = getattr(self, k)
            if issubclass(type(v), list):
                v = Serializer.serialize_list(v, full=full)
            elif issubclass(type(v), Serializer):
                if full:
                    v = v.serialize(full=False)
                else:
                    continue
            s[k] = v
        return s

    @staticmethod
    def serialize_list(l, full=True):
        return [m.serialize(full=full) for m in l]
