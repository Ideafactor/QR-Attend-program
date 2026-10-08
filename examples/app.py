"""Run with uvicorn examples.app:app. Set ATTENDANCE_ADMIN_TOKEN first."""

import hmac
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from attendance_fastapi import AttendanceConfig, create_attendance, create_employee_router
from attendance_fastapi.schemas import RuleInput
from attendance_sqlalchemy import SqlAlchemyRepository
from examples.kbw import scanner_router

engine = create_async_engine(
    os.getenv("ATTENDANCE_DATABASE_URL", "sqlite+aiosqlite:///./attendance.db")
)
repository = SqlAlchemyRepository(async_sessionmaker(engine, expire_on_commit=False))
attendance = create_attendance(
    repository,
    config=AttendanceConfig(
        mobile_base_url=os.getenv("ATTENDANCE_MOBILE_URL", "http://localhost:5177/c"),
        qr_signing_secret=os.getenv("ATTENDANCE_QR_SIGNING_SECRET"),
    ),
)


@asynccontextmanager
async def lifespan(app):
    await repository.create_schema(engine)  # example only; use Alembic in production
    import json
    from pathlib import Path

    rule = RuleInput(**json.loads(Path(__file__).with_name("work-rule.json").read_text()))
    await attendance.seed_rules(rule)
    yield
    await engine.dispose()


def require_admin(authorization: str | None = Header(default=None)):
    expected = os.getenv("ATTENDANCE_ADMIN_TOKEN")
    if expected and authorization and hmac.compare_digest(authorization, "Bearer " + expected):
        return "example-admin"
    return None


app = FastAPI(title="Attendance example", lifespan=lifespan)
app.include_router(attendance.router(require_admin), prefix="/api/attendance")
app.include_router(scanner_router(attendance, token=lambda: os.getenv("ATTENDANCE_SCANNER_TOKEN")))


# Demo mapping is server-configured. Real hosts resolve an authenticated session instead.
def require_employee(authorization: str | None = Header(default=None)):
    expected = os.getenv("ATTENDANCE_EMPLOYEE_TOKEN")
    if (
        expected
        and authorization
        and hmac.compare_digest(authorization.encode(), ("Bearer " + expected).encode())
    ):
        return os.getenv("ATTENDANCE_EMPLOYEE_ID")
    return None


app.include_router(create_employee_router(attendance, require_employee), prefix="/api/attendance")
