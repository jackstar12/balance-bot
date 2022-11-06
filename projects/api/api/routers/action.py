from fastapi import APIRouter

from api.crudrouter import add_crud_routes
from database.dbmodels.action import Action
from database.models.action import ActionInfo, ActionCreate

router = APIRouter(
    tags=["action"],
    prefix="/action"
)

add_crud_routes(
    router,
    table=Action,
    read_schema=ActionInfo,
    create_schema=ActionCreate
)
