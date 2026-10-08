"""Initial attendance tables. Schema v1 is immutable after release.
Revision ID: att_0001
"""

from alembic import op
from attendance_sqlalchemy.schema_v1 import build_schema

revision = "att_0001"
down_revision = None
branch_labels = ("attendance",)
depends_on = None


def upgrade():
    metadata, _ = build_schema()
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    metadata, _ = build_schema()
    metadata.drop_all(op.get_bind(), checkfirst=False)
