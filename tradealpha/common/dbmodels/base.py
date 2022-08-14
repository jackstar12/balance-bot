from tradealpha.common.models import BaseModel


class OrmBaseModel(BaseModel):
    class Config:
        orm_mode = True
