import operator
from datetime import datetime
from typing import Any, Type, TypeVar, Generic

from database.dbsync import BaseMixin
from database.models import BaseModel
from database.models.document import Operator


def excludes(a, b):
    return ~operator.contains(a, b)


class FilterMixin:
    @classmethod
    def apply(cls, param: 'FilterParam', stmt):
        raise ValueError

    @classmethod
    def validator(cls, field: str):
        raise ValueError


T = TypeVar('T', bound=BaseMixin)


class FilterParam(BaseModel, Generic[T]):
    field: str
    op: Operator = Operator.EQ
    values: list[Any]

    @classmethod
    def parse(cls, key: str, raw_values: list[Any], table: Type[FilterMixin], model: Type[BaseModel] = None):
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

        values = []

        if model and field in model.__fields__:
            compare_field = model.__fields__[field]

            if op in ('includes', 'excludes'):
                values, errors = compare_field.validate(raw_values, {}, loc='none')
                if errors:
                    raise ValueError('Invalid input value')
            else:
                for value in raw_values:
                    validated, errors = compare_field.validate(value, {}, loc='none')
                    if errors:
                        raise ValueError('Invalid input value')
                    values.append(validated)
        elif table:
            validate = table.validator(field)

            if not validate:
                compare_field = getattr(table, field)
                validate = compare_field.expression.name.python_type

                if validate == datetime:
                    validate = datetime.fromisoformat

            for value in raw_values:
                validated = validate(value)
                values.append(validated)

        else:
            raise ValueError('Unknown field')

        return cls(
            field=field,
            op=op,
            values=values
        )

    @property
    def cmp_func(self):
        if self.op == Operator.EXCLUDES:
            return excludes
        elif self.op == Operator.INCLUDES:
            return operator.contains
        else:
            return getattr(operator, str(self.op.value))

    def apply(self, stmt, table: Type[FilterMixin]):

        try:
            return table.apply(self, stmt)
        except ValueError:
            pass

        col = getattr(table, self.field)
        cmp_func = self.cmp_func

        return stmt.where(*[
            cmp_func(col, value)
            for value in self.values
        ])

    def check(self, other: T):
        compare_value = getattr(other, self.field)
        return any(self.cmp_func(compare_value, value) for value in self.values)
