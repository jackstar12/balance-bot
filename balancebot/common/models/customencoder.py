import json
import dataclasses
from datetime import datetime


class CustomEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.timestamp()

        return json.JSONEncoder.default(self, o)

