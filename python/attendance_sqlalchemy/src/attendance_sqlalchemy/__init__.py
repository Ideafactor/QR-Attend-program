"""Tenant-scoped SQLAlchemy repository with serialized write transactions."""

import hashlib
from contextlib import asynccontextmanager
from datetime import date, datetime
from sqlalchemy import Date, DateTime, delete, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from .schema_v2 import build_schema

metadata, tables = build_schema()


class SqlTransaction:
    def __init__(self, session, tenant):
        self.session, self.tenant = session, tenant

    def condition(self, table, key):
        return (table.c.tenant_id == self.tenant) & (table.c.id == key)

    async def get(self, table, key):
        model = tables[table]
        return (
            await self.session.execute(select(model.c.data).where(self.condition(model, key)))
        ).scalar_one_or_none()

    async def list(self, table):
        model = tables[table]
        return list(
            (
                await self.session.execute(
                    select(model.c.data).where(model.c.tenant_id == self.tenant)
                )
            ).scalars()
        )

    async def put(self, table, key, data):
        model = tables[table]
        values = {"data": data}
        for column in model.columns:
            if column.name in ("id", "tenant_id", "data"):
                continue
            value = data.get(column.name)
            if value is not None and isinstance(column.type, DateTime):
                value = datetime.fromisoformat(value)
            elif value is not None and isinstance(column.type, Date):
                value = date.fromisoformat(value)
            values[column.name] = value
        previous = await self.get(table, key)
        if previous is None:
            await self.session.execute(
                insert(model).values(tenant_id=self.tenant, id=key, **values)
            )
        else:
            if table == "scans" and data != previous:
                # Explicit retention may erase GPS, never alter the scan's identity/judgment.
                redacted = {**previous, "lat": None, "lng": None, "accuracy_m": None}
                if data != redacted:
                    raise ValueError(
                        "scans are append-only; only retention GPS redaction is allowed"
                    )
            if table in ("qr_uses", "scan_resolutions"):
                raise ValueError(f"{table} is append-only")
            await self.session.execute(
                update(model).where(self.condition(model, key)).values(**values)
            )

    async def delete(self, table, key):
        model = tables[table]
        await self.session.execute(delete(model).where(self.condition(model, key)))


class SqlAlchemyRepository:
    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory

    @asynccontextmanager
    async def transaction(self, tenant_id="default"):
        async with self.session_factory() as session:
            dialect = session.bind.dialect.name
            if dialect == "sqlite":
                # SQLite test/example database: serialize writers across processes too.
                await session.execute(text("BEGIN IMMEDIATE"))
            elif dialect == "postgresql":
                key = int.from_bytes(
                    hashlib.sha256(tenant_id.encode()).digest()[:8], "big", signed=True
                )
                await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
            else:
                raise ValueError("supported databases: PostgreSQL and SQLite")
            try:
                yield SqlTransaction(session, tenant_id)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def create_schema(self, engine: AsyncEngine):
        """Development convenience. Production should apply packaged Alembic revisions."""
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
