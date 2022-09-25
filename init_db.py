# inside of a "create the database" script, first create
# tables:
from tradealpha.common.dbsync import Base, engine
import tradealpha.common.dbmodels as dbmodels
from alembic.config import Config
from alembic import command

Base.metadata.create_all(engine)

# then, load the Alembic configuration and generate the
# version table, "stamping" it with the most recent rev:
alembic_cfg = Config("alembic.ini")
command.stamp(alembic_cfg, "head")
