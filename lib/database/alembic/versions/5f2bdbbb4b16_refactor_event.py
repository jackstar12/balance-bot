"""refactor event

Revision ID: 5f2bdbbb4b16
Revises: 150590cb8130
Create Date: 2022-10-16 11:58:43.954821

"""
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '5f2bdbbb4b16'
down_revision = '150590cb8130'
branch_labels = None
depends_on = None


def upgrade():
    session = Session(bind=op.get_bind())
    # ### commands auto generated by Alembic - please adjust! ###



    op.create_table('evententry',
                    sa.Column('client_id', sa.Integer(), nullable=False),
                    sa.Column('event_id', sa.Integer(), nullable=False),
                    sa.Column('init_balance_id', sa.Integer(), nullable=True),
                    sa.Column('rekt_on', sa.DateTime(timezone=True), nullable=True),
                    sa.ForeignKeyConstraint(['client_id'], ['client.id'], ondelete='CASCADE'),
                    sa.ForeignKeyConstraint(['event_id'], ['event.id'], ondelete='CASCADE'),
                    sa.ForeignKeyConstraint(['init_balance_id'], ['balance.id'], ondelete='CASCADE'),
                    sa.PrimaryKeyConstraint('client_id', 'event_id')
                    )

    op.drop_constraint('eventscore_client_id_event_id_last_rank_update_fkey', 'eventscore', type_='foreignkey')
    op.drop_constraint('eventscore_init_balance_id_fkey', 'eventscore', type_='foreignkey')

    op.drop_table('eventrank')

    op.add_column('eventscore', sa.Column('time', sa.DateTime(timezone=True), nullable=False))
    op.add_column('eventscore', sa.Column('rank', sa.Integer(), nullable=True))
    op.drop_column('eventscore', 'init_balance_id')
    op.drop_column('eventscore', 'rekt_on')
    op.drop_column('eventscore', 'last_rank_update')

    # ### end Alembic commands ###


def downgrade():
    session = Session(bind=op.get_bind())
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('journal', 'chapter_interval',
                    existing_type=sa.Enum('DAY', 'WEEK', 'MONTH', name='intervaltype'),
                    type_=postgresql.INTERVAL(),
                    existing_nullable=True)
    op.add_column('eventscore', sa.Column('last_rank_update', postgresql.TIMESTAMP(timezone=True), autoincrement=False,
                                          nullable=True))
    op.add_column('eventscore',
                  sa.Column('rekt_on', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True))
    op.add_column('eventscore', sa.Column('init_balance_id', sa.INTEGER(), autoincrement=False, nullable=True))
    op.create_foreign_key('eventscore_init_balance_id_fkey', 'eventscore', 'balance', ['init_balance_id'], ['id'],
                          ondelete='CASCADE')
    op.create_foreign_key('eventscore_client_id_event_id_last_rank_update_fkey', 'eventscore', 'eventrank',
                          ['client_id', 'event_id', 'last_rank_update'], ['client_id', 'event_id', 'time'])
    op.drop_column('eventscore', 'rank')
    op.drop_column('eventscore', 'time')
    op.create_table('eventrank',
                    sa.Column('client_id', sa.INTEGER(), autoincrement=False, nullable=False),
                    sa.Column('event_id', sa.INTEGER(), autoincrement=False, nullable=False),
                    sa.Column('value', sa.INTEGER(), autoincrement=False, nullable=False),
                    sa.Column('time', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False),
                    sa.ForeignKeyConstraint(['client_id'], ['client.id'], name='eventrank_client_id_fkey',
                                            ondelete='CASCADE'),
                    sa.ForeignKeyConstraint(['event_id'], ['event.id'], name='eventrank_event_id_fkey',
                                            ondelete='CASCADE'),
                    sa.PrimaryKeyConstraint('client_id', 'event_id', 'time', name='eventrank_pkey')
                    )
    op.drop_table('evententry')
    # ### end Alembic commands ###