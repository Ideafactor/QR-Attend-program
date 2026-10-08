from datetime import date, datetime
from importlib import import_module
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from attendance_sqlalchemy import metadata, tables


async def test_initial_migration_roundtrip_and_typed_columns(env):
    revision = import_module("attendance_sqlalchemy.migrations.versions.0001_attendance")
    async with env.engine.begin() as connection:
        await connection.run_sync(metadata.drop_all)

        def upgrade(conn):
            with Operations.context(MigrationContext.configure(conn)):
                revision.upgrade()
            columns = {c["name"]: c for c in inspect(conn).get_columns("att_scans")}
            assert "scanned_at" in columns and "employee_id" in columns

        await connection.run_sync(upgrade)
    async with env.repo.transaction("default") as tx:
        await tx.put(
            "attendance",
            "employee:2026-09-28",
            {
                "id": "employee:2026-09-28",
                "employee_id": "employee",
                "work_date": "2026-09-28",
                "in_at": "2026-09-28T00:00:00+00:00",
            },
        )
    async with env.engine.connect() as connection:
        row = (
            await connection.execute(
                select(tables["attendance"].c.work_date, tables["attendance"].c.in_at)
            )
        ).one()
        assert row.work_date == date(2026, 9, 28) and isinstance(row.in_at, datetime)
    try:
        async with env.repo.transaction("default") as tx:
            await tx.put(
                "attendance",
                "different-key",
                {"id": "different-key", "employee_id": "employee", "work_date": "2026-09-28"},
            )
    except IntegrityError:
        pass
    else:
        raise AssertionError("employee-day unique constraint must reject duplicate records")
    async with env.engine.begin() as connection:

        def downgrade(conn):
            with Operations.context(MigrationContext.configure(conn)):
                revision.downgrade()
            assert "att_scans" not in inspect(conn).get_table_names()

        await connection.run_sync(downgrade)


async def test_alembic_runner_is_repeatable(env):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    import attendance_sqlalchemy

    root = Path(__file__).resolve().parents[1]
    async with env.engine.begin() as connection:
        await connection.run_sync(metadata.drop_all)

        def run(conn):
            config = Config()
            config.set_main_option("path_separator", "os")
            config.set_main_option("script_location", str(root / "examples/alembic"))
            config.set_main_option(
                "version_locations",
                str(Path(attendance_sqlalchemy.__file__).parent / "migrations/versions"),
            )
            config.attributes["connection"] = conn
            command.upgrade(config, "attendance@head")
            command.upgrade(config, "attendance@head")
            assert (
                conn.execute(text("SELECT version_num FROM att_alembic_version")).scalar_one()
                == "att_0002"
            )
            command.downgrade(config, "base")
            assert "att_attendance" not in inspect(conn).get_table_names()

        await connection.run_sync(run)


async def test_v2_upgrade_preserves_v1_data_and_downgrade_only_removes_additions(env):
    from attendance_sqlalchemy.schema_v1 import build_schema as build_v1

    v1 = import_module("attendance_sqlalchemy.migrations.versions.0001_attendance")
    v2 = import_module("attendance_sqlalchemy.migrations.versions.0002_rotating_qr")
    old_metadata, old_tables = build_v1()
    async with env.engine.begin() as connection:
        await connection.run_sync(metadata.drop_all)

        def migrate(conn):
            with Operations.context(MigrationContext.configure(conn)):
                v1.upgrade()
                conn.execute(
                    old_tables["employees"]
                    .insert()
                    .values(tenant_id="default", id="kept", data={"id": "kept", "name": "Existing"})
                )
                v2.upgrade()
                assert (
                    conn.execute(select(old_tables["employees"].c.data)).scalar_one()["name"]
                    == "Existing"
                )
                assert "att_qr_uses" in inspect(conn).get_table_names()
                v2.downgrade()
                assert "att_qr_uses" not in inspect(conn).get_table_names()
                assert "att_scans" in inspect(conn).get_table_names()
                assert (
                    conn.execute(select(old_tables["employees"].c.data)).scalar_one()["id"]
                    == "kept"
                )
                v2.upgrade()

        await connection.run_sync(migrate)


async def test_raw_scan_and_consumption_ledger_are_append_only(env):
    import pytest

    async with env.repo.transaction() as tx:
        raw = {"id": "scan", "employee_id": "employee", "result": "already_in"}
        await tx.put("scans", "scan", raw)
        with pytest.raises(ValueError, match="append-only"):
            await tx.put("scans", "scan", {**raw, "result": "out"})
        await tx.put("qr_uses", "hash", {"id": "hash", "employee_id": "employee"})
        with pytest.raises(ValueError, match="append-only"):
            await tx.put("qr_uses", "hash", {"id": "hash", "employee_id": "other"})
