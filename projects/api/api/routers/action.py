from api.crudrouter import create_crud_router
from common.dbmodels.action import Action
from common.models.action import ActionInfo, ActionCreate

router = create_crud_router(
    prefix='/action',
    table=Action,
    read_schema=ActionInfo,
    create_schema=ActionCreate
)
