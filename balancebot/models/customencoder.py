import json
import dataclasses
from datetime import datetime


class CustomEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.timestamp()
        elif dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)

        return json.JSONEncoder.default(self, o)

