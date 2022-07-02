import operator
from datetime import datetime
from decimal import Decimal

import pytz
from sqlalchemy import Column, Integer, ForeignKey, String, Table, orm, Numeric, delete, DateTime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, Session
from sqlalchemy.ext.hybrid import hybrid_property

from tradealpha.common.dbsync import Base
from tradealpha.common.dbasync import async_session, db
from tradealpha.common.dbmodels.amountmixin import AmountMixin
from tradealpha.common.dbmodels.pnldata import PnlData
from tradealpha.common.dbmodels.serializer import Serializer
from tradealpha.common.dbmodels.execution import Execution
from tradealpha.common.enums import Side, ExecType, Status
from tradealpha.common.messenger import NameSpace, Category, Messenger
from tradealpha.common.models.pnldata import PnlData as CompactPnlData
from tradealpha.common import utils
from tradealpha.common.dbmodels.symbol import CurrencyMixin

trade_association = Table('trade_association', Base.metadata,
                          Column('trade_id', ForeignKey('trade.id', ondelete="CASCADE"), primary_key=True),
                          Column('label_id', ForeignKey('label.id', ondelete="CASCADE"), primary_key=True)
                          )


class Trade(Base, Serializer, CurrencyMixin):
    __tablename__ = 'trade'
    __serializer_forbidden__ = ['client', 'initial']

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('client.id', ondelete="CASCADE"), nullable=False)
    client = relationship('Client', lazy='noload')
    labels = relationship('Label', lazy='noload', secondary=trade_association, backref='trades')

    symbol = Column(String, nullable=False)
    entry = Column(Numeric, nullable=False)

    qty = Column(Numeric, nullable=False)
    open_qty = Column(Numeric, nullable=False)
    transferred_qty = Column(Numeric, nullable=True)
    open_time: datetime = Column(DateTime(timezone=True), nullable=False)

    exit = Column(Numeric, nullable=True)
    realized_pnl = Column(Numeric, nullable=True, default=Decimal(0))
    total_commissions = Column(Numeric, nullable=True, default=Decimal(0))

    init_balance_id = Column(Integer, ForeignKey('balance.id', ondelete='SET NULL'), nullable=True)
    init_balance = relationship(
        'Balance',
        lazy='noload',
        foreign_keys=init_balance_id,
        uselist=False
    )

    max_pnl_id = Column(Integer, ForeignKey('pnldata.id', ondelete='SET NULL'), nullable=True)
    max_pnl: PnlData = relationship(
        'PnlData',
        lazy='noload',
        foreign_keys=max_pnl_id,
        post_update=True
    )

    min_pnl_id = Column(Integer, ForeignKey('pnldata.id', ondelete='SET NULL'), nullable=True)
    min_pnl: PnlData = relationship(
        'PnlData',
        lazy='noload',
        foreign_keys=min_pnl_id,
        post_update=True
    )

    tp = Column(Numeric, nullable=True)
    sl = Column(Numeric, nullable=True)

    order_count = Column(Integer, nullable=True)

    executions = relationship('Execution',
                              foreign_keys='[Execution.trade_id]',
                              back_populates='trade',
                              lazy='noload',
                              cascade='all, delete',
                              order_by="Execution.time")

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
        primaryjoin='Execution.id == Trade.initial_execution_id'

    )

    memo = Column(String, nullable=True)

    @orm.reconstructor
    def init_on_load(self):
        self.live_pnl: PnlData = None
        self.latest_pnl: PnlData = utils.list_last(self.pnl_data, None)

    def __init__(self, upnl: Decimal = None, *args, **kwargs):
        self.live_pnl: PnlData = PnlData(
            unrealized=upnl,
            realized=self.realized_pnl,
            time=datetime.now(pytz.utc)
        )
        self.latest_pnl: PnlData = utils.list_last(self.pnl_data, None)
        super().__init__(*args, **kwargs)

    @hybrid_property
    def label_ids(self):
        return [str(label.id) for label in self.labels]

    @hybrid_property
    def side(self):
        return (self.initial or self.executions[0]).side

    @hybrid_property
    def size(self):
        return self.entry * self.qty

    @hybrid_property
    def account_gain(self):
        return self.realized_pnl / self.init_balance.unrealized

    @hybrid_property
    def account_size_init(self):
        return self.size / self.init_balance.unrealized

    @hybrid_property
    def net_pnl(self):
        return self.realized_pnl - self.total_commisions

    @hybrid_property
    def compact_pnl_data(self):
        return [
            CompactPnlData(
                ts=int(pnl_data.time.timestamp()),
                realized=pnl_data.realized,
                unrealized=pnl_data.unrealized
            ) for pnl_data in self.pnl_data
        ]

    @classmethod
    def is_data(cls):
        return True

    @hybrid_property
    def close_time(self):
        return utils.list_last(self.executions).time

    @hybrid_property
    def is_open(self):
        return self.open_qty > Decimal(0)

    @hybrid_property
    def risk_to_reward(self):
        if self.tp and self.sl:
            return (self.tp - self.entry) / (self.entry - self.sl)

    @hybrid_property
    def realized_r(self):
        if self.sl:
            return (self.exit - self.entry) / (self.entry - self.sl)

    @hybrid_property
    def fomo_ratio(self):
        if self.max_pnl.total != self.min_pnl.total:
            return 1 - (self.max_pnl.total / (self.max_pnl.total - self.min_pnl.total))

    @hybrid_property
    def greed_ratio(self):
        if self.max_pnl.total:
            return 1 - self.realized_pnl / self.max_pnl.total
        return 0
        if self.realized_pnl:
            return self.max_pnl.total / self.realized_pnl

    @hybrid_property
    def status(self):
        return (
            Status.OPEN if self.open_qty != 0
            else
            Status.WIN if self.realized_pnl > 0 else Status.LOSS
        )

    async def serialize(self, data=True, full=True, *args, **kwargs):
        s = await super().serialize(*args, data=data, full=full, **kwargs)
        if s:
            s['status'] = 'open' if self.open_qty > Decimal(0) else 'win' if self.realized_pnl > Decimal(0) else 'loss'
        return s

    def calc_rpnl(self):
        realized_qty = self.qty - self.open_qty - self.transferred_qty
        diff = self.exit - self.entry
        raw = diff / realized_qty if self.inverse else diff * realized_qty
        return raw * (1 if self.initial.side == Side.BUY else -1)

    def calc_upnl(self, price: Decimal):
        diff = price - self.entry
        if self.open_qty != 0:
            return (diff / self.open_qty if self.inverse else diff * self.open_qty) * (
                Decimal(1) if self.initial.side == Side.BUY else Decimal(-1))
        else:
            return 0

    def update_pnl(self, price: Decimal,
                   messenger: Messenger = None,
                   realtime=True,
                   commit=False,
                   now: datetime = None,
                   extra_currencies: dict[str, Decimal] = None):

        if not now:
            now = datetime.now(pytz.utc)
        upnl = self.calc_upnl(price)
        self.live_pnl = PnlData(
            trade_id=self.id,
            unrealized=upnl,
            realized=self.realized_pnl,
            time=now,
            extra_currencies={
                currency: rate * upnl
                for currency, rate in extra_currencies if currency != self.settle
            } if extra_currencies else None
        )

        self._replace_pnl(self.max_pnl, self.live_pnl, Decimal.__ge__)
        self._replace_pnl(self.min_pnl, self.live_pnl, Decimal.__le__)
        self.latest_pnl = self._compare_pnl(self.latest_pnl,
                                            self.live_pnl,
                                            lambda latest, live: (
                                                    not latest or abs((latest - live) / latest) > Decimal(.25)
                                            ))
        if realtime and messenger:
            messenger.pub_channel(NameSpace.TRADE, Category.UPNL, channel_id=self.client_id,
                                  obj={'id': self.id, 'upnl': upnl})

    async def reverse_to(self,
                         date: datetime,
                         db_session: AsyncSession,
                         commit=True):

        if date < self.initial.time:
            # if we reverse to beyond existense of the trade, straight up
            # delete it
            await db_session.delete(self)
        else:
            removals = False
            for execution in reversed(self.executions):
                if execution.time > date:
                    # If the side of the execution equals the side of the trade,
                    # remove_qty will be positive, so the size of the trade decreases
                    remove_qty = execution.effective_qty * self.initial.side.value
                    if execution.type == ExecType.TRANSFER:
                        self.transferred_qty -= remove_qty
                    else:
                        self.open_qty -= remove_qty
                    self.qty -= remove_qty
                    await db_session.delete(execution)
                    removals = True
            if removals:
                await db_session.execute(
                    delete(PnlData).filter(
                        PnlData.trade_id == self.id,
                        PnlData.time > date
                    )
                )

        if commit:
            await db_session.commit()

    def _replace_pnl(self, old: PnlData, new: PnlData, cmp_func):
        if not old or cmp_func(new.total, old.total):
            self.max_pnl.unrealized = self.live_pnl.unrealized
            self.max_pnl.realized = self.live_pnl.realized
            self.max_pnl.time = self.live_pnl.time

    def _compare_pnl(self, old: PnlData, new: PnlData, cmp_func):
        if not old or cmp_func(new.total, old.total):
            Session.object_session(self).add(new)
            # TODO: Should the PNL objects be persisted in db before publishing them?
            # self._messenger.pub_channel(NameSpace.TRADE, Category.SIGNIFICANT_PNL, channel_id=trade.client_id,
            #                            obj={'id': self.id, 'pnl': new.amount})
            return new
        return old


def trade_from_execution(execution: Execution):
    trade = Trade(
        entry=execution.price,
        qty=execution.qty,
        open_time=execution.time,
        open_qty=execution.qty if execution.type == ExecType.TRADE else Decimal(0),
        transferred_qty=execution.qty if execution.type == ExecType.TRANSFER else Decimal(0),
        initial=execution,
        total_commissions=execution.commission,
        symbol=execution.symbol,
        executions=[execution],
        inverse=execution.inverse,
        settle=execution.settle
    )
    execution.trade = trade
    pnl = PnlData(
        trade=trade,
        realized=0,
        unrealized=0,
        time=execution.time
    )
    trade.max_pnl = trade.min_pnl = pnl
    return trade
