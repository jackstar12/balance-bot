from pydantic import BaseModel


class OrmBaseModel(BaseModel):
    class Config:
        orm_mode = True
