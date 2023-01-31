from typing import Optional

from database.models import OrmBaseModel, OutputID
from database.models.document import DocumentModel


class PageInfo(OrmBaseModel):
    id: OutputID
    title: Optional[str]
    #group: Optional[str]
    data: Optional[dict]

    #balances: List[Balance]
    #performance: Optional[Gain]
    #start_balance: FullBalance
    #end_balance: FullBalance

class FullPage(PageInfo):
    doc: DocumentModel

    #balances: List[Balance]
    #performance: Optional[Gain]
    #start_balance: FullBalance
    #end_balance: FullBalance

