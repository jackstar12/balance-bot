from api.database import db
from api.dbmodels.serializer import Serializer
from sqlalchemy.ext.hybrid import hybrid_property
from api.dbmodels.execution import Execution


class Trade(db.Model, Serializer):
    """
    Init buy:
    1 BTC@40k 12:00


    """
    __tablename__ = 'trade'
    __serializer_forbidden__ = ['client_id']

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id', ondelete="CASCADE"), nullable=True)

    symbol = db.Column(db.String, nullable=False)
    entry = db.Column(db.Float, nullable=False)

    qty = db.Column(db.Float, nullable=False)
    open_qty = db.Column(db.Float, nullable=False)
    exit = db.Column(db.Float, nullable=True)
    realized_pnl = db.Column(db.Float, nullable=True)

    executions = db.relationship('Execution', foreign_keys='[Execution.trade_id]', backref='trade', lazy=True,
                                 cascade='all, delete')

    initial_execution_id = db.Column(db.Integer, db.ForeignKey('execution.id'), nullable=True)

    initial = db.relationship(
        'Execution',
        lazy=True,
        foreign_keys=[initial_execution_id, symbol],
        post_update=True,
        primaryjoin='Execution.id == Trade.initial_execution_id',
        backref='init_trade',
        uselist=False
    )

    label = db.Column(db.String, nullable=True)
    memo = db.Column(db.String, nullable=True)

    def is_data(self):
        return True

    @hybrid_property
    def is_open(self):
        return self.exit is not None

    def serialize(self, data=True, full=True):
        s = super().serialize(data, full)
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
