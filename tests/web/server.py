"""Deterministic clock for browser tests only; never used by the example app."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from time import monotonic
from examples.app import app, attendance, engine, repository
from attendance_fastapi.schemas import RuleInput

started = monotonic()
attendance.clock = lambda: (
    datetime.fromisoformat("2026-09-29T09:05:00+09:00") + timedelta(seconds=monotonic() - started)
)


@asynccontextmanager
async def lifespan(app):
    await repository.create_schema(engine)
    await attendance.seed_rules(
        RuleInput(
            name="브라우저 테스트",
            effective_from="2026-09-01",
            is_default=True,
            check_in_slots=["09:00", "09:30", "10:00", "10:30", "11:00"],
            checkout_mode="elapsed",
            dedup_seconds=0,
        )
    )
    yield
    await engine.dispose()


app.router.lifespan_context = lifespan
