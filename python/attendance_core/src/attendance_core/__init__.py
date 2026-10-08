"""Dependency-free attendance policy. All clocks are supplied by the caller."""

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Literal
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
UTC = timezone.utc


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(UTC)


def instant(value: str | datetime | None) -> datetime | None:
    return (
        aware(datetime.fromisoformat(value) if isinstance(value, str) else value) if value else None
    )


def local_day(value: datetime) -> date:
    return aware(value).astimezone(SEOUL).date()


def minute(value: str) -> int:
    parsed = time.fromisoformat(value)
    if len(value) != 5 or parsed.second or parsed.microsecond or parsed.tzinfo:
        raise ValueError("time must be HH:MM")
    return parsed.hour * 60 + parsed.minute


def at(day: date, value: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(value), SEOUL).astimezone(UTC)


@dataclass(frozen=True)
class Rules:
    check_in_start: str = "08:00"
    work_start: str | None = None
    check_in_end: str = "11:00"
    check_out_start: str = "18:00"
    check_in_slots: tuple[str, ...] = ()
    slot_grace_minutes: int = 10
    checkout_mode: Literal["fixed", "elapsed"] = "fixed"
    checkout_offset_minutes: int = 540
    missing_in_out_start: str = "18:00"
    after_slots: Literal["pending", "late"] = "pending"
    dedup_seconds: int = 60

    def __post_init__(self):
        start, end, out = map(
            minute, (self.check_in_start, self.check_in_end, self.check_out_start)
        )
        minute(self.missing_in_out_start)
        object.__setattr__(self, "check_in_slots", tuple(self.check_in_slots))
        if self.checkout_mode not in ("fixed", "elapsed") or self.after_slots not in (
            "pending",
            "late",
        ):
            raise ValueError("invalid rule mode")
        if self.dedup_seconds < 0 or self.slot_grace_minutes < 0:
            raise ValueError("intervals cannot be negative")
        if not 0 < self.checkout_offset_minutes < 1440:
            raise ValueError("checkout offset must be between 1 and 1439 minutes")
        if self.check_in_slots:
            slots = [minute(s) for s in self.check_in_slots]
            if slots != sorted(set(slots)) or start > slots[0]:
                raise ValueError("slots must be sorted, unique and after check_in_start")
            cutoff = minute(self.missing_in_out_start) if self.checkout_mode == "elapsed" else out
            if slots[-1] + self.slot_grace_minutes >= cutoff:
                raise ValueError("missing-in cutoff must follow the last slot grace window")
            if self.checkout_mode == "elapsed" and slots[-1] + self.checkout_offset_minutes >= 1440:
                raise ValueError("overnight rules are not supported")
            if self.checkout_mode == "fixed" and slots[-1] + self.slot_grace_minutes >= out:
                raise ValueError("checkout must follow the slot window")
        else:
            if not start < end <= out:
                raise ValueError("require check_in_start < check_in_end <= check_out_start")
            if self.work_start and not start <= minute(self.work_start) < end:
                raise ValueError("work_start must fall within the check-in window")

    def snapshot(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DayRecord:
    work_date: date
    in_at: datetime | None = None
    credited_in_at: datetime | None = None
    expected_out_at: datetime | None = None
    out_at: datetime | None = None
    in_kind: str | None = None
    out_kind: str | None = None
    protected: bool = False

    @classmethod
    def from_dict(cls, value: dict):
        return cls(
            work_date=date.fromisoformat(value["work_date"]),
            **{
                k: instant(value.get(k))
                for k in ("in_at", "credited_in_at", "expected_out_at", "out_at")
            },
            in_kind=value.get("in_kind"),
            out_kind=value.get("out_kind"),
            protected=value.get("protected", False),
        )

    def to_dict(self) -> dict:
        return {
            k: v.isoformat() if isinstance(v, (date, datetime)) else v
            for k, v in asdict(self).items()
        }


@dataclass(frozen=True)
class Judgement:
    kind: str
    record: DayRecord | None
    pending_reason: str | None = None


def credited_time(now: datetime, rules: Rules) -> datetime | None:
    day = local_day(now)
    if rules.check_in_slots:
        for slot in rules.check_in_slots:
            candidate = at(day, slot)
            if now < candidate + timedelta(minutes=rules.slot_grace_minutes + 1):
                return candidate
        return None
    return now


def expected_out(credited: datetime, rules: Rules) -> datetime:
    result = (
        credited + timedelta(minutes=rules.checkout_offset_minutes)
        if rules.checkout_mode == "elapsed"
        else at(local_day(credited), rules.check_out_start)
    )
    if local_day(result) != local_day(credited):
        raise ValueError("overnight rules are not supported")
    return result


def judge_scan(
    now_utc: datetime,
    record: DayRecord | None,
    rules: Rules,
    *,
    last_scan: datetime | None = None,
    pending_reason: str | None = None,
    force_out: bool = False,
) -> Judgement:
    now = aware(now_utc)
    day = local_day(now)
    if record and record.work_date != day:
        raise ValueError("record is not for the scan's Seoul date")
    if last_scan and 0 <= (now - aware(last_scan)).total_seconds() < rules.dedup_seconds:
        return Judgement("duplicate", record)
    if pending_reason:
        return Judgement("pending", record, pending_reason)
    if record and record.protected:
        return Judgement("protected", record)
    current = record or DayRecord(day)
    if not force_out and now < at(day, rules.check_in_start):
        return Judgement("pending", record, "early_hours")
    missing_cutoff = (
        rules.check_out_start if rules.checkout_mode == "fixed" else rules.missing_in_out_start
    )
    if force_out or current.in_at or now >= at(day, missing_cutoff):
        if current.in_at and now <= current.in_at:
            return Judgement("already_in", record)
        if current.in_at and not force_out:
            scheduled = current.expected_out_at or expected_out(
                current.credited_in_at or current.in_at, rules
            )
            if now < scheduled:
                return Judgement("already_in", record)
        latest = max(now, current.out_at) if current.out_at else now
        kind = "early" if current.expected_out_at and latest < current.expected_out_at else "normal"
        updated = replace(
            current, out_at=latest, out_kind=kind if current.in_at else None, protected=force_out
        )
        return Judgement(
            "out_no_in" if not current.in_at else "early_out" if kind == "early" else "out", updated
        )
    credited = credited_time(now, rules)
    late = now >= at(day, rules.check_in_end) if not rules.check_in_slots else credited is None
    if credited is None:
        if rules.after_slots == "pending":
            return Judgement("pending", record, "outside_schedule")
        credited = now
    tardy = bool(
        not rules.check_in_slots
        and rules.work_start
        and now >= at(day, rules.work_start) + timedelta(minutes=1)
    )
    kind = "late" if late else "tardy" if tardy else "normal"
    try:
        expected = expected_out(credited, rules)
    except ValueError:
        return Judgement("pending", record, "outside_schedule")
    return Judgement(
        {"normal": "in", "tardy": "tardy_in", "late": "late_in"}[kind],
        replace(
            current, in_at=now, credited_in_at=credited, expected_out_at=expected, in_kind=kind
        ),
    )


def approve_scan(
    scanned_at: datetime,
    record: DayRecord | None,
    rules: Rules,
    action: Literal["in", "out", "prev_out"],
) -> DayRecord:
    scanned_at = aware(scanned_at)
    day = local_day(scanned_at) - timedelta(days=action == "prev_out")
    current = record or DayRecord(day)
    if current.work_date != day or current.protected:
        raise ValueError("approval conflicts with a protected record or work date")
    if action == "in":
        actual = min(scanned_at, current.in_at) if current.in_at else scanned_at
        if current.out_at and actual >= current.out_at:
            raise ValueError("approved check-in must precede checkout")
        credited = credited_time(actual, rules) or actual
        return replace(
            current,
            in_at=actual,
            credited_in_at=credited,
            expected_out_at=expected_out(credited, rules),
            in_kind="approved",
            protected=True,
        )
    if action not in ("out", "prev_out"):
        raise ValueError("invalid approval action")
    if current.in_at and scanned_at <= current.in_at:
        raise ValueError("checkout must be after check-in")
    latest = max(scanned_at, current.out_at) if current.out_at else scanned_at
    return replace(current, out_at=latest, out_kind="approved", protected=True)


def distance_m(lat: float, lng: float, site_lat: float, site_lng: float) -> float:
    for a, b in ((lat, lng), (site_lat, site_lng)):
        if not isfinite(a) or not isfinite(b) or not -90 <= a <= 90 or not -180 <= b <= 180:
            raise ValueError("invalid coordinates")
    p1, p2 = radians(lat), radians(site_lat)
    delta = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(site_lng - lng) / 2) ** 2
    return 6371008.8 * 2 * asin(sqrt(min(1, max(0, delta))))
