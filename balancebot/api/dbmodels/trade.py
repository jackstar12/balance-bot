from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType, Table, orm
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.api.database import Base, Meta
from balancebot.api.dbmodels.serializer import Serializer
from balancebot.api.dbmodels.execution import Execution

trade_association = Table('trade_association', Base.metadata,
                          Column('trade_id', ForeignKey('trade.id', ondelete="CASCADE"), primary_key=True),
                          Column('label_id', ForeignKey('label.id', ondelete="CASCADE"), primary_key=True)
                          )


class Trade(Base, Serializer):
    __tablename__ = 'trade'
    __serializer_forbidden__ = ['client', 'initial']

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('client.id', ondelete="CASCADE"), nullable=False)
    client = relationship('Client')
    labels = relationship('Label', secondary=trade_association, backref='trades')

    symbol = Column(String, nullable=False)
    entry = Column(Float, nullable=False)

    qty = Column(Float, nullable=False)
    open_qty = Column(Float, nullable=False)
    exit = Column(Float, nullable=True)

    realized_pnl = Column(Float, nullable=True)

    max_pnl_id = Column(Integer, ForeignKey('pnldata.id', ondelete='SET NULL'), nullable=True)
    max_pnl = relationship('PnlData', lazy='raise', foreign_keys=max_pnl_id, uselist=False)

    min_pnl_id = Column(Integer, ForeignKey('pnldata.id', ondelete='SET NULL'), nullable=True)
    min_pnl = relationship('PnlData', lazy='raise', foreign_keys=min_pnl_id, uselist=False)

    # tp = Column(Float, nullable=True)
    # sl = Column(Float, nullable=True)

    executions = relationship('Execution',
                              foreign_keys='[Execution.trade_id]',
                              backref='trade',
                              lazy='noload',
                              cascade='all, delete')

    pnl_data = relationship('PnlData',
                            lazy='noload',
                            cascade="all, delete",
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

    @orm.reconstructor
    def init_on_load(self):
        self.upnl = None

    def __init__(self, upnl: float = None, *args, **kwargs):
        self.upnl = upnl
        super().__init__(*args, **kwargs)

    @classmethod
    def is_data(cls):
        return True

    @hybrid_property
    def is_open(self):
        return self.open_qty > 0.0

    async def serialize(self, data=True, full=True, *args, **kwargs):
        s = await super().serialize(data, full, *args, **kwargs)
        if s:
            s['status'] = 'open' if self.open_qty > 0 else 'win' if self.realized_pnl > 0.0 else 'loss'
        return s

    def calc_rpnl(self):
        realized_qty = self.qty - self.open_qty
        return (self.exit * realized_qty - self.entry * realized_qty) * (1 if self.initial.side == 'BUY' else -1)

    def calc_upnl(self, price: float):
        return (price * self.open_qty - self.entry * self.open_qty) * (1 if self.initial.side == 'BUY' else -1)


def trade_from_execution(execution: Execution):
    return Trade(
        entry=execution.price,
        qty=execution.qty,
        open_qty=execution.qty,
        initial=execution,
        symbol=execution.symbol,
        executions=[execution]
    )
