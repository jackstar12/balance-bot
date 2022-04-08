from dataclasses import dataclass


@dataclass
class SelectionOption:
    name: str
    value: str
    description: str
    object: object
