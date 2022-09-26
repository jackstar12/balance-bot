from tradealpha.api.crudrouter import create_crud_router
from tradealpha.common.dbmodels.action import Action
from tradealpha.common.models.action import ActionInfo, ActionCreate

router = create_crud_router(
    prefix='/action',
    table=Action,
    read_schema=ActionInfo,
    create_schema=ActionCreate
)
