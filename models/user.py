from dataclasses import dataclass


@dataclass
class User:
    name: str
    password: str  # Salted hash
    salt: str

    def get_id(self):
        return f'{self.name}{self.password}{self.salt}'.encode('utf-8')

    def __hash__(self):
        return self.get_id()
