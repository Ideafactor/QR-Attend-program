"""QR consumption ledger and immutable scan resolution overlay."""

from alembic import op
from sqlalchemy import MetaData
from attendance_sqlalchemy.schema_v2 import add_v2_tables

revision = "att_0002"
down_revision = "att_0001"
branch_labels = None
depends_on = None


def upgrade():
    metadata = MetaData()
    add_v2_tables(metadata)
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    metadata = MetaData()
    add_v2_tables(metadata)
    metadata.drop_all(op.get_bind(), checkfirst=False)
