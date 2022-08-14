import operator
from enum import Enum
from typing import Any, Type, TypeVar

from pydantic import ValidationError, Field, create_model
from pydantic.validators import find_validators
from starlette.requests import Request

from api.models.trade import DetailledTrade
from tradealpha.api.models import BaseModel


class Operator(Enum):
    GT = "gt"
    LT = "lt"
    EQ = "eq"
    NE = "ne"


T = TypeVar('T', bound=BaseModel)


class FilterParam(BaseModel):
    field: str
    op: Operator = Operator.EQ
    values: list[Any]

    @classmethod
    def parse(cls, key: str, raw_values: list[Any], other: Type[BaseModel]):
        if key.endswith(']'):
            split = key[:-1].split('[')
        else:
            raise ValueError('Invalid key')

        if len(split) != 2:
            raise ValueError('Invalid key')

        field = split[0]
        op = split[1]

        compare_field = other.__fields__.get(field)

        if not compare_field:
            raise ValueError('Invalid key')

        values = []
        for value in raw_values:
            validated, errors = compare_field.validate(value, {}, loc='none')
            if errors:
                raise ValueError('Invalid input value')
            values.append(validated)

        return cls(
            field=field,
            op=op,
            values=values
        )

    def check(self, other: BaseModel):
        compare_value = getattr(other, self.field)

        checked = False
        for value in self.values:
            checked = getattr(operator, self.op.value)(compare_value, value)
            if checked:
                break
        return checked




