import json
import dataclasses
from datetime import datetime
from Models.client import Client


class CustomEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.timestamp()
        elif dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)

        return json.JSONEncoder.default(self, o)


class CustomDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        super().__init__(object_hook=self.object_hook, *args, **kwargs)

    def object_hook(self, dct):

        return dct

