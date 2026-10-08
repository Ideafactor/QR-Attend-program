from datetime import datetime
import os
import uuid
from sqlalchemy import text
from types import SimpleNamespace
import pytest_asyncio
from fastapi import FastAPI, Header
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from attendance_core import Rules
from attendance_fastapi import create_attendance, AttendanceConfig
from attendance_sqlalchemy import SqlAlchemyRepository


@pytest_asyncio.fixture
async def env(tmp_path):
    database_url = os.getenv("ATTENDANCE_TEST_DATABASE_URL")
    schema = "test_" + uuid.uuid4().hex
    bootstrap = None
    if database_url:
        if not database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("tests require postgresql+asyncpg")
        bootstrap = create_async_engine(database_url)
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            database_url, connect_args={"server_settings": {"search_path": schema}}
        )
    else:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path}/test.db", connect_args={"timeout": 30}
        )
    repo = SqlAlchemyRepository(async_sessionmaker(engine, expire_on_commit=False))
    await repo.create_schema(engine)
    clock = SimpleNamespace(value=datetime.fromisoformat("2026-09-28T09:00:00+09:00"))
    app = FastAPI()
    service = create_attendance(
        repo,
        config=AttendanceConfig(
            employee_qr_mode="static",
            rules=Rules(
                check_in_slots=("09:00", "09:30", "10:00", "10:30", "11:00"),
                checkout_mode="elapsed",
            ),
        ),
        clock=lambda: clock.value,
        tenant_resolver=lambda r: r.headers.get("X-Tenant", "default"),
    )

    def admin(x_admin: str | None = Header(default=None)):
        return "tester" if x_admin == "test-admin" else None

    app.include_router(service.router(admin), prefix="/att")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"X-Admin": "test-admin"}
    ) as client:
        yield SimpleNamespace(
            service=service, repo=repo, engine=engine, client=client, clock=clock, app=app
        )
    await engine.dispose()
    if bootstrap:
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()
