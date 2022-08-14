from pydantic import BaseModel as PydanticBaseModel


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


class BaseOrmModel(BaseModel):
    class Config:
        orm_mode = True
