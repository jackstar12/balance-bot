from api.database import db
from api.dbmodels.serializer import Serializer
from sqlalchemy.ext.hybrid import hybrid_property
from api.dbmodels.execution import Execution


trade_association = db.Table('trade_association',
                             db.Column('trade_id', db.ForeignKey('trade.id', ondelete="CASCADE"), primary_key=True),
                             db.Column('label_id', db.ForeignKey('label.id', ondelete="CASCADE"), primary_key=True)
                             )


class Trade(db.Model, Serializer):

    __tablename__ = 'trade'
    __serializer_forbidden__ = ['client', 'initial']

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id', ondelete="CASCADE"), nullable=False)
    labels = db.relationship('Label', secondary=trade_association, backref='trades')

    symbol = db.Column(db.String, nullable=False)
    entry = db.Column(db.Float, nullable=False)

    qty = db.Column(db.Float, nullable=False)
    open_qty = db.Column(db.Float, nullable=False)
    exit = db.Column(db.Float, nullable=True)
    realized_pnl = db.Column(db.Float, nullable=True)

    executions = db.relationship('Execution', foreign_keys='[Execution.trade_id]', backref='trade', lazy=True,
                                 cascade='all, delete')

    initial_execution_id = db.Column(db.Integer, db.ForeignKey('execution.id', ondelete="SET NULL"), nullable=True)

    initial = db.relationship(
        'Execution',
        lazy=True,
        foreign_keys=[initial_execution_id, symbol],
        post_update=True,
        primaryjoin='Execution.id == Trade.initial_execution_id',
        backref='init_trade',
        uselist=False
    )

    memo = db.Column(db.String, nullable=True)

    def is_data(self):
        return True

    @hybrid_property
    def is_open(self):
        return self.exit is not None

    def serialize(self, data=True, full=True, *args, **kwargs):
        s = super().serialize(data, full, *args, **kwargs)
        if s:
            s['status'] = 'open' if self.open_qty > 0 else 'win' if self.realized_pnl > 0.0 else 'loss'
        return s


def trade_from_execution(execution: Execution):
    return Trade(
        entry=execution.price,
        qty=execution.qty,
        open_qty=execution.qty,
        initial=execution,
        symbol=execution.symbol,
        executions=[execution]
    )
