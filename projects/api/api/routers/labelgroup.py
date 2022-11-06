from fastapi import APIRouter

from api.crudrouter import add_crud_routes, Route
from api.models.labelinfo import LabelGroupInfo, LabelGroupCreate
from database.dbmodels.label import LabelGroup as LabelGroupDB

router = APIRouter(
    prefix="/label/group"
)

add_crud_routes(router,
                table=LabelGroupDB,
                read_schema=LabelGroupInfo,
                create_schema=LabelGroupCreate,
                default_route=Route(
                    eager_loads=[LabelGroupDB.labels]
                ))
