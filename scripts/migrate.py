"""Standalone example migration runner; host apps may integrate version_locations instead."""

import argparse
import asyncio
import os
from pathlib import Path
from alembic.config import Config
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine
import attendance_sqlalchemy


async def migrate(url, revision):
    config = Config()
    config.set_main_option("path_separator", "os")
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "examples" / "alembic")
    )
    config.set_main_option(
        "version_locations",
        str(Path(attendance_sqlalchemy.__file__).parent / "migrations" / "versions"),
    )
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:

            def run(sync_connection):
                config.attributes["connection"] = sync_connection
                command.upgrade(config, revision)

            await connection.run_sync(run)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("revision", nargs="?", default="attendance@head")
    args = parser.parse_args()
    asyncio.run(
        migrate(
            os.environ.get("ATTENDANCE_DATABASE_URL", "sqlite+aiosqlite:///./attendance.db"),
            args.revision,
        )
    )
