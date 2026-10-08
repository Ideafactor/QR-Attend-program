from alembic import context
from attendance_sqlalchemy import metadata

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use scripts/migrate.py or supply a host SQLAlchemy connection")
context.configure(
    connection=connection, target_metadata=metadata, version_table="att_alembic_version"
)
with context.begin_transaction():
    context.run_migrations()
