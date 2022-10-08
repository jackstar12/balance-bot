from api.crudrouter import create_crud_router
from database.dbmodels.action import Action
from database.models.action import ActionInfo, ActionCreate

router = create_crud_router(
    prefix='/action',
    table=Action,
    read_schema=ActionInfo,
    create_schema=ActionCreate
)
