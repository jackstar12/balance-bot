from api.crudrouter import create_crud_router
from api.models.labelinfo import LabelGroupInfo, LabelGroupCreate
from database.dbmodels.label import LabelGroup as LabelGroupDB

router = create_crud_router(prefix="/label/group",
                            table=LabelGroupDB,
                            read_schema=LabelGroupInfo,
                            create_schema=LabelGroupCreate,
                            eager_loads=[LabelGroupDB.labels])
