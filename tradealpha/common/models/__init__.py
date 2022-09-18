from typing import Type, Union

from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB

from tradealpha.common import customjson


InputID = Union[int, str]
OutputID = str


class BaseModel(PydanticBaseModel):
    @classmethod
    def construct(cls, _fields_set=None, **values):
        m = cls.__new__(cls)
        fields_values = {}

        config = cls.__config__

        for name, field in cls.__fields__.items():
            key = field.alias
            # Added this to allow population by field name
            if key not in values and config.allow_population_by_field_name:
                key = name

            if key in values:
                # Moved this check since None value can be passed for Optional nested field
                if values[key] is None and not field.required:
                    fields_values[name] = field.get_default()
                else:
                    if issubclass(field.type_, BaseModel):
                        if isinstance(values[key], field.type_):
                            fields_values[name] = values[key]
                        elif field.shape == 2:
                            fields_values[name] = [
                                e if isinstance(e, field.type_) else field.type_.construct(**e)
                                for e in values[key]
                            ]
                        elif field.shape == 12:
                            fields_values[name] = {
                                k: e if isinstance(e, field.type_) else field.type_.construct(**e)
                                for k, e in values[key].items()
                            }
                        else:
                            fields_values[name] = field.outer_type_.construct(**values[key])
                    else:
                        fields_values[name] = values[key]
            elif not field.required:
                fields_values[name] = field.get_default()

        object.__setattr__(m, '__dict__', fields_values)
        if _fields_set is None:
            _fields_set = set(values.keys())
        object.__setattr__(m, '__fields_set__', _fields_set)
        m._init_private_attributes()
        return m

    @classmethod
    def get_sa_type(cls, validate=False, **dict_options) -> Type[TypeDecorator]:


        class SAType(TypeDecorator):
            impl = JSONB

            def process_bind_param(self, value, dialect):
                if isinstance(value, cls):
                    return value.dict(**dict_options)
                return value

            def process_result_value(self, value, dialect):
                if value:
                    if validate:
                        return cls(**value)
                    return cls.construct(**value)
                return value

        return SAType



class OrmBaseModel(BaseModel):
    class Config:
        orm_mode = True

__all__ = [
    "OrmBaseModel",
    "BaseModel",
    "InputID",
    "OutputID"
]