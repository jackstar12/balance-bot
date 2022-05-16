from decimal import Decimal
from typing import List, Dict, TypeVar

from pydantic import BaseModel
from balancebot.common.enums import Filter


T = TypeVar('T')


class TradeAnalytics(BaseModel):
    id: int

    labels = relationship('Label', secondary=trade_association, backref='trades')

    symbol: str
    entry: Decimal

    qty: Decimal
    open_qty: Decimal

    exit: Decimal
    transferred_qty: Decimal
    realized_pnl: Decimal

    max_pnl = relationship('PnlData', lazy='noload', foreign_keys=max_pnl_id, uselist=False)

    min_pnl = relationship('PnlData', lazy='noload', foreign_keys=min_pnl_id, uselist=False)

    tp = Decimal
    sl = Decimal

    order_count = Column(Integer, nullable=True)

    executions = relationship('Execution',
                              foreign_keys='[Execution.trade_id]',
                              backref='trade',
                              lazy='noload',
                              cascade='all, delete')

    pnl_data = relationship('PnlData',
                            lazy='noload',
                            cascade="all, delete",
                            back_populates='trade',
                            foreign_keys="PnlData.trade_id")

    initial_execution_id = Column(Integer, ForeignKey('execution.id', ondelete="SET NULL"), nullable=True)

    initial: Execution = relationship(
        'Execution',
        lazy='joined',
        foreign_keys=initial_execution_id,
        post_update=True,
        primaryjoin='Execution.id == Trade.initial_execution_id',
        uselist=False
    )

    memo = Column(String, nullable=True)




class Performance(BaseModel):
    relative: Decimal
    absolute: Decimal
    filter_values: Dict[Filter, Decimal]


class FilteredPerformance(BaseModel):
    filters: List[filter]
    performance: Performance


class ClientAnalytics(BaseModel):
    id: int
    filtered_performance: FilteredPerformance
    trades: List[TradeAnalytics]
