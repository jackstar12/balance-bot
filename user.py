import dataclasses
from client import Client


@dataclasses.dataclass
class User:
    id: int
    api: Client
