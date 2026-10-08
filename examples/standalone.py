"""Standalone development host: uvicorn app:app. Production uses host migrations/auth."""

import hmac
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from attendance_fastapi import AttendanceConfig, create_attendance, create_scanner_router
from attendance_sqlalchemy import SqlAlchemyRepository

engine = create_async_engine(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./attendance.db"))
repository = SqlAlchemyRepository(async_sessionmaker(engine, expire_on_commit=False))
attendance = create_attendance(
    repository, config=AttendanceConfig(qr_signing_secret=os.getenv("ATTENDANCE_QR_SIGNING_SECRET"))
)


@asynccontextmanager
async def lifespan(app):
    await repository.create_schema(engine)  # local development only
    yield
    await engine.dispose()


def admin(authorization: str | None = Header(default=None)):
    expected = os.getenv("ATTENDANCE_ADMIN_TOKEN")
    if (
        expected
        and authorization
        and hmac.compare_digest(authorization.encode(), ("Bearer " + expected).encode())
    ):
        return "standalone-admin"
    return None


app = FastAPI(lifespan=lifespan)
app.include_router(attendance.router(admin), prefix="/api/attendance")
app.include_router(
    create_scanner_router(
        attendance, token=lambda: os.getenv("ATTENDANCE_SCANNER_TOKEN"), prefix="/api/scanner"
    )
)
