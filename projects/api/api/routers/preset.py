from fastapi import APIRouter

from api.crudrouter import add_crud_routes
from api.models.preset import PresetInfo, PresetCreate
from database.dbmodels.editing.preset import Preset

router = APIRouter(
    prefix="/presets"
)

add_crud_routes(router,
                table=Preset,
                read_schema=PresetInfo,
                create_schema=PresetCreate,)
