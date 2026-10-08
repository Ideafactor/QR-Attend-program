from datetime import date, datetime
import os
import time
import pytest
from attendance_core import Rules, judge_scan, approve_scan, distance_m


def stamp(value):
    return datetime.fromisoformat("2026-09-28T" + value + "+09:00")


def slots(**kwargs):
    return Rules(
        check_in_slots=("09:00", "09:30", "10:00", "10:30", "11:00"),
        checkout_mode="elapsed",
        **kwargs,
    )


@pytest.mark.parametrize(
    "scan,credited,out",
    [
        ("09:00:00", "09:00", "18:00"),
        ("09:10:59.999999", "09:00", "18:00"),
        ("09:11:00", "09:30", "18:30"),
        ("09:40:59", "09:30", "18:30"),
        ("09:41:00", "10:00", "19:00"),
        ("10:41:00", "11:00", "20:00"),
        ("11:10:59", "11:00", "20:00"),
    ],
)
def test_slot_boundaries(scan, credited, out):
    record = judge_scan(stamp(scan), None, slots()).record
    assert record.credited_in_at == stamp(credited)
    assert record.expected_out_at == stamp(out)
    assert record.in_at == stamp(scan)
    assert record.out_at is None


def test_pending_and_no_in():
    assert judge_scan(stamp("07:59:59"), None, slots()).pending_reason == "early_hours"
    assert judge_scan(stamp("11:11:00"), None, slots()).pending_reason == "outside_schedule"
    result = judge_scan(stamp("20:00"), None, slots())
    assert result.kind == "out_no_in"
    assert result.record.in_at is None and result.record.expected_out_at is None


def test_latest_and_protected_override():
    rules = slots()
    first = judge_scan(stamp("09:08"), None, rules).record
    early = judge_scan(stamp("09:35"), first, rules)
    assert early.kind == "already_in"
    assert early.record == first and early.record.out_at is None
    last = judge_scan(stamp("18:12"), early.record, rules)
    assert last.kind == "out" and last.record.in_at == stamp("09:08")
    override = judge_scan(stamp("09:20"), first, rules, force_out=True)
    assert override.record.protected
    assert judge_scan(stamp("18:12"), override.record, rules).record == override.record


@pytest.mark.parametrize(
    "clock,kind",
    [
        ("09:00:59", "in"),
        ("09:01:00", "tardy_in"),
        ("10:59:59", "tardy_in"),
        ("11:00:00", "late_in"),
    ],
)
def test_fixed(clock, kind):
    assert judge_scan(stamp(clock), None, Rules(work_start="09:00")).kind == kind


def test_duplicate_does_not_consume_override():
    first = judge_scan(stamp("09:00"), None, slots()).record
    assert (
        judge_scan(stamp("09:00:59"), first, slots(), last_scan=stamp("09:00"), force_out=True).kind
        == "duplicate"
    )
    assert judge_scan(stamp("09:01"), first, slots(), last_scan=stamp("09:00")).kind == "already_in"


def test_previous_month_approval():
    scan = datetime.fromisoformat("2026-10-01T00:30:00+09:00")
    record = approve_scan(scan, None, Rules(), "prev_out")
    assert record.work_date == date(2026, 9, 30) and record.out_at == scan


def test_server_os_timezone_independent():
    old = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        assert judge_scan(stamp("09:10"), None, slots()).record.credited_in_at == stamp("09:00")
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_invalid_rules_and_coordinates():
    with pytest.raises(ValueError):
        Rules(work_start="07:00")
    with pytest.raises(ValueError):
        slots(checkout_offset_minutes=900)
    assert distance_m(37, 127, 37, 127) == 0
    with pytest.raises(ValueError):
        distance_m(float("nan"), 127, 37, 127)
