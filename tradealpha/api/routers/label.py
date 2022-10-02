from typing import Any

from tradealpha.api.crudrouter import create_crud_router
from tradealpha.api.models.labelinfo import CreateLabel
from tradealpha.api.models.labelinfo import LabelInfo, LabelGroupInfo, LabelGroupCreate
from tradealpha.common.dbmodels.client import add_client_filters
from tradealpha.common.dbmodels.label import Label as LabelDB, LabelGroup as LabelGroupDB
from tradealpha.common.dbmodels.trade import Trade
from tradealpha.common.dbmodels.user import User


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

group_router = create_crud_router(prefix="/label/group",
                                  table=LabelGroupDB,
                                  read_schema=LabelGroupInfo,
                                  create_schema=LabelGroupCreate,
                                  eager_loads=[LabelGroupDB.labels])

group_router.include_router(router)
router = group_router

#router.include_router(group_router)


def add_trade_filters(stmt, user: User, trade_id: int):
    return add_client_filters(
        stmt.filter(
            Trade.id == trade_id,
        ).join(Trade.client),
        user
    )


#@router.post('/trade')
#async def add_label(body: AddLabel,
#                    user: User = Depends(CurrentUser),
#                    db: AsyncSession = Depends(get_db)):
#    verify_trade_id = await db_exec(
#        add_trade_filters(
#            select(TradeDB.id),
#            user=user,
#            trade_id=body.trade_id
#        ),
#        session=db
#    )
#
#    if not verify_trade_id:
#        return BadRequest('Invalid Trade ID')
#
#    verify_label_id = await db_select(
#        LabelDB,
#        id=body.label_id,
#        user_id=user.id,
#        session=db
#    )
#
#    if not verify_label_id:
#        return BadRequest('Invalid Label ID')
#
#    await db.execute(
#        insert(trade_association).values(
#            trade_id=body.trade_id,
#            label_id=body.label_id
#        ),
#    )
#    await db.commit()
#
#    return OK('Success')
#
#
#@router.delete('/trade')
#async def remove_label(body: RemoveLabel,
#                       user: User = Depends(CurrentUser),
#                       db: AsyncSession = Depends(get_db)):
#    trade = await db_first(
#        add_trade_filters(select(Trade), user, body.trade_id),
#        Trade.labels
#    )
#    label = await db_first(
#        select(LabelDB).filter(
#            LabelDB.id == body.label_id,
#        )
#    )
#    if label:
#        if label in trade.labels:
#            trade.labels.remove(label)
#        else:
#            return BadRequest('Trade already has this label')
#    else:
#        return NotFound('Invalid Label ID')
