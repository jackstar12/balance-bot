import operator
from enum import Enum
from typing import Any, Type, TypeVar, Generic

from database.models import BaseModel


class Operator(Enum):
    GT = "gt"
    LT = "lt"
    EQ = "eq"
    NE = "ne"
    INCLUDES = "includes"
    EXCLUDES = "excludes"


def excludes(a, b):
    return ~operator.contains(a, b)


T = TypeVar('T', bound=BaseModel)


class FilterParam(BaseModel, Generic[T]):
    field: str
    op: Operator = Operator.EQ
    values: list[Any]

    @classmethod
    def parse(cls, key: str, raw_values: list[Any], other: Type[T]):
        # Key format:
        # key[operator]
        # e.g. realized_pnl[gt]
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
            if op in ('includes', 'excludes'):
                value = [value]
            validated, errors = compare_field.validate(value, {}, loc='none')
            if errors:
                raise ValueError('Invalid input value')
            if op in ('includes', 'excludes'):
                validated = validated[0]
            values.append(validated)

        return cls(
            field=field,
            op=op,
            values=values
        )

    def check(self, other: T):
        compare_value = getattr(other, self.field)
        for value in self.values:
            if self.op == Operator.EXCLUDES:
                cmp_func = excludes
            elif self.op == Operator.INCLUDES:
                cmp_func = operator.contains
            else:
                cmp_func = getattr(operator, str(self.op.value))
            if cmp_func(compare_value, value):
                return True
        return False
