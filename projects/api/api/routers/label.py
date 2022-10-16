from typing import Any

from api.crudrouter import create_crud_router
from api.models.labelinfo import CreateLabel
from api.models.labelinfo import LabelInfo
from database.dbmodels.label import Label as LabelDB, LabelGroup as LabelGroupDB
from database.dbmodels.user import User


def label_filter(stmt: Any, user: User):
    return stmt.join(
        LabelDB.group
    ).where(
        LabelGroupDB.user_id == user.id
    )


router = create_crud_router(prefix="/label",
                            table=LabelDB,
                            read_schema=LabelInfo,
                            create_schema=CreateLabel,
                            add_filters=label_filter)
