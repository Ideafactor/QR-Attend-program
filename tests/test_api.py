import asyncio
from datetime import datetime
from fastapi import HTTPException
import pytest


def set_time(env, value):
    env.clock.value = datetime.fromisoformat(value + "+09:00")


async def employee(env, name="직원"):
    response = await env.client.post("/att/employees", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def test_scans_override_and_protection(env):
    person = await employee(env)
    code, eid = person["qr_token"], person["id"]
    first = await env.service.record_scan(code)
    assert first["result"] == "in"
    response = await env.client.put(
        f"/att/employees/{eid}/scan-override",
        json={
            "mode": "out",
            "label": "조퇴",
            "reason": "긴급",
            "expires_at": "2026-09-28T10:00:00+09:00",
        },
    )
    assert response.status_code == 200, response.text
    set_time(env, "2026-09-28T09:00:30")
    assert (await env.service.record_scan(code))["result"] == "duplicate"
    assert (await env.client.get(f"/att/employees/{eid}/scan-override")).json()[
        "consumed_at"
    ] is None
    set_time(env, "2026-09-28T09:20:00")
    results = await asyncio.gather(env.service.record_scan(code), env.service.record_scan(code))
    assert sorted(r["result"] for r in results) == ["duplicate", "early_out"]
    set_time(env, "2026-09-28T18:00:00")
    assert (await env.service.record_scan(code))["result"] == "protected"
    record = (await env.client.get("/att/attendance")).json()[0]
    assert record["out_at"] == "2026-09-28T09:20:00+09:00"
    assert record["label"] == "조퇴"


async def test_tenant_and_admin_isolation(env):
    person = await employee(env)
    response = await env.client.get("/att/employees", headers={"X-Admin": ""})
    assert response.status_code == 403
    response = await env.client.patch(
        f"/att/employees/{person['id']}", json={"name": "bad"}, headers={"X-Tenant": "other"}
    )
    assert response.status_code == 404
    with pytest.raises(HTTPException) as error:
        await env.service.record_scan(person["qr_token"], tenant_id="other")
    assert error.value.status_code == 404


async def test_rule_versions_and_date_exception(env):
    person = await employee(env)
    base = {
        "name": "기본",
        "effective_from": "2026-09-01",
        "is_default": True,
        "check_in_slots": ["09:00", "09:30", "10:00", "10:30", "11:00"],
        "checkout_mode": "elapsed",
    }
    response = await env.client.post("/att/work-rules", json=base)
    assert response.status_code == 201, response.text
    rule = response.json()
    video = {**base, "name": "영상팀", "is_default": False, "check_in_slots": ["13:00"]}
    video_rule = (await env.client.post("/att/work-rules", json=video)).json()
    response = await env.client.put(
        f"/att/employees/{person['id']}/rule-exception",
        json={"rule_id": video_rule["id"], "date": "2026-09-29", "reason": "촬영 보고"},
    )
    assert response.status_code == 200, response.text
    set_time(env, "2026-09-29T13:05:00")
    result = await env.service.record_scan(person["qr_token"])
    assert result["record"]["expected_out_at"] == "2026-09-29T13:00:00+00:00"
    response = await env.client.patch(
        f"/att/work-rules/{rule['id']}",
        json={**base, "effective_from": "2026-10-01", "checkout_offset_minutes": 480},
    )
    assert response.status_code == 200, response.text
    result = (
        await env.client.get(f"/att/employees/{person['id']}/effective-rule?date=2026-09-30")
    ).json()
    assert result["checkout_offset_minutes"] == 540
    result = (
        await env.client.get(f"/att/employees/{person['id']}/effective-rule?date=2026-10-01")
    ).json()
    assert result["checkout_offset_minutes"] == 480


async def register_mobile(env, person):
    invite = (await env.client.post(f"/att/employees/{person['id']}/mobile-invite")).json()
    response = await env.client.post(
        "/att/mobile/register",
        json={"code": invite["code"], "consent": True, "consent_version": "1"},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"], invite["code"]


async def test_mobile_geofence_override_approval_and_revoke(env):
    person = await employee(env)
    await env.service.record_scan(person["qr_token"])
    auth, code = await register_mobile(env, person)
    assert (
        await env.client.post(
            "/att/mobile/register", json={"code": code, "consent": True, "consent_version": "1"}
        )
    ).status_code == 401
    site = (
        await env.client.post("/att/sites", json={"name": "현장", "lat": 37, "lng": 127})
    ).json()
    await env.client.put(
        f"/att/employees/{person['id']}/scan-override",
        json={"label": "휴가", "reason": "긴급", "expires_at": "2026-09-28T11:00:00+09:00"},
    )
    set_time(env, "2026-09-28T10:00:00")
    response = await env.client.post(
        "/att/mobile/checkins",
        headers={"Authorization": "Bearer " + auth},
        json={"site_token": site["qr_token"], "lat": 38, "lng": 127, "accuracy": 5},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["pending_reason"] == "outside_geofence"
    assert (
        await env.client.post(f"/att/pending/{result['scan_id']}/approve", json={"as": "in"})
    ).status_code == 409
    response = await env.client.post(
        f"/att/pending/{result['scan_id']}/approve", json={"as": "out"}
    )
    assert response.status_code == 200, response.text
    assert (await env.client.get("/att/attendance")).json()[0]["label"] == "휴가"
    await env.client.delete(f"/att/employees/{person['id']}/mobile-device")
    assert (
        await env.client.get("/att/mobile/me", headers={"Authorization": "Bearer " + auth})
    ).status_code == 403


async def test_missing_in_and_retention_settings(env):
    person = await employee(env)
    set_time(env, "2026-09-28T20:00:00")
    result = await env.service.record_scan(person["qr_token"])
    assert result["result"] == "out_no_in"
    assert result["record"]["credited_in_at"] is None
    assert (
        await env.client.put("/att/settings", json={"records_years_after_exit": 2})
    ).status_code == 422


async def test_qr_rotation_invalidates_old_and_refresh_token(env):
    person = await employee(env)
    auth, _ = await register_mobile(env, person)
    site = (
        await env.client.post("/att/sites", json={"name": "현장", "lat": 37, "lng": 127})
    ).json()
    await env.client.post(f"/att/sites/{site['id']}/qr/reissue")
    response = await env.client.post(
        "/att/mobile/checkins",
        headers={"Authorization": "Bearer " + auth},
        json={"site_token": site["qr_token"], "lat": 37, "lng": 127, "accuracy": 5},
    )
    assert response.status_code == 404
    response = await env.client.post(
        "/att/mobile/token/refresh", headers={"Authorization": "Bearer " + auth}
    )
    assert response.status_code == 200
    assert (
        await env.client.get("/att/mobile/me", headers={"Authorization": "Bearer " + auth})
    ).status_code == 401
    assert (
        await env.client.get(
            "/att/mobile/me", headers={"Authorization": "Bearer " + response.json()["token"]}
        )
    ).status_code == 200


async def test_concurrent_invite_and_override_other_employee(env):
    person = await employee(env)
    invite = (await env.client.post(f"/att/employees/{person['id']}/mobile-invite")).json()
    body = {"code": invite["code"], "consent": True, "consent_version": "1"}
    results = await asyncio.gather(
        env.client.post("/att/mobile/register", json=body),
        env.client.post("/att/mobile/register", json=body),
    )
    assert sorted(r.status_code for r in results) == [200, 401]
    await env.client.put(
        f"/att/employees/{person['id']}/scan-override",
        json={"label": "조퇴", "reason": "긴급", "expires_at": "2026-09-28T10:00:00+09:00"},
    )
    second = await employee(env, "다른 직원")
    assert (await env.service.record_scan(second["qr_token"]))["result"] == "in"
    override = (await env.client.get(f"/att/employees/{person['id']}/scan-override")).json()
    assert override["consumed_at"] is None
    set_time(env, "2026-09-28T10:01:00")
    assert (await env.service.record_scan(person["qr_token"]))["result"] == "in"
    assert (
        (await env.client.get(f"/att/employees/{person['id']}/scan-override"))
        .json()
        .get("expired_at")
    )


async def test_display_device_scope_and_expiry(env):
    person = await employee(env)
    auth, _ = await register_mobile(env, person)
    site = (
        await env.client.post(
            "/att/sites", json={"name": "현장", "lat": 37, "lng": 127, "qr_mode": "rotating"}
        )
    ).json()
    device = (
        await env.client.post("/att/devices", json={"name": "태블릿", "site_id": site["id"]})
    ).json()
    display = (
        await env.client.post("/att/devices/register", json={"code": device["code"]})
    ).json()["token"]
    url = f"/att/sites/{site['id']}/qr/current"
    assert (
        await env.client.get(url, headers={"Authorization": "Bearer " + auth})
    ).status_code == 401
    qr = (await env.client.get(url, headers={"Authorization": "Bearer " + display})).json()
    set_time(env, "2026-09-28T09:00:31")
    response = await env.client.post(
        "/att/mobile/checkins",
        headers={"Authorization": "Bearer " + auth},
        json={"site_token": qr["site_token"], "lat": 37, "lng": 127, "accuracy": 5},
    )
    assert response.status_code == 410
    await env.client.delete(f"/att/devices/{device['id']}")
    assert (
        await env.client.get(url, headers={"Authorization": "Bearer " + display})
    ).status_code == 403


async def test_manual_protection_approval_conflict_and_csv(env):
    person = await employee(env)
    response = await env.client.post(
        "/att/attendance",
        json={
            "employee_id": person["id"],
            "work_date": "2026-09-28",
            "in_at": "2026-09-28T09:08:00+09:00",
            "memo": "=FORMULA()",
        },
    )
    assert response.status_code == 201, response.text
    set_time(env, "2026-09-28T18:00:00")
    assert (await env.service.record_scan(person["qr_token"]))["result"] == "protected"
    exported = await env.client.get("/att/export?month=2026-09")
    assert "'=FORMULA()" in exported.text
    assert (await env.client.get("/att/export?month=oops")).status_code == 422


async def test_unassign_preserves_history_and_manual_validation(env):
    person = await employee(env)
    base = {"name": "기본", "effective_from": "2026-09-01", "is_default": True}
    await env.client.post("/att/work-rules", json=base)
    rule = (
        await env.client.post(
            "/att/work-rules",
            json={**base, "name": "직원", "is_default": False, "work_start": "10:00"},
        )
    ).json()
    path = f"/att/employees/{person['id']}/work-rule"
    assert (
        await env.client.put(path, json={"rule_id": rule["id"], "effective_from": "2026-09-01"})
    ).status_code == 200
    assert (
        await env.client.put(path, json={"rule_id": None, "effective_from": "2026-10-01"})
    ).status_code == 200
    before = (
        await env.client.get(f"/att/employees/{person['id']}/effective-rule?date=2026-09-30")
    ).json()
    after = (
        await env.client.get(f"/att/employees/{person['id']}/effective-rule?date=2026-10-01")
    ).json()
    assert before["work_start"] == "10:00" and after["work_start"] is None
    response = await env.client.post(
        "/att/attendance",
        json={
            "employee_id": person["id"],
            "work_date": "2026-09-28",
            "out_at": "2026-10-15T18:00:00+09:00",
        },
    )
    assert response.status_code == 422


async def test_rejudge_updates_rules_but_preserves_manual_days(env):
    person = await employee(env)
    payload = {
        "name": "기본",
        "effective_from": "2026-09-01",
        "is_default": True,
        "check_in_slots": ["09:00", "09:30", "10:00", "10:30", "11:00"],
        "checkout_mode": "elapsed",
    }
    rule = (await env.client.post("/att/work-rules", json=payload)).json()
    await env.service.record_scan(person["qr_token"])
    set_time(env, "2026-09-28T18:00:00")
    await env.service.record_scan(person["qr_token"])
    await env.client.post(
        "/att/attendance",
        json={
            "employee_id": person["id"],
            "work_date": "2026-09-27",
            "in_at": "2026-09-27T09:00:00+09:00",
        },
    )
    new = (
        await env.client.patch(
            "/att/work-rules/" + rule["id"],
            json={**payload, "effective_from": "2026-10-01", "checkout_offset_minutes": 480},
        )
    ).json()
    response = await env.client.post(
        "/att/work-rules/" + new["id"] + "/rejudge", json={"from": "2026-09-27", "to": "2026-09-28"}
    )
    assert response.status_code == 200 and response.json()["updated"] == 1
    rows = {r["work_date"]: r for r in (await env.client.get("/att/attendance")).json()}
    assert rows["2026-09-28"]["expected_out_at"] == "2026-09-28T17:00:00+09:00"
    assert rows["2026-09-27"]["expected_out_at"] == "2026-09-27T18:00:00+09:00"


async def test_rejudge_does_not_leave_stale_record_if_all_scans_become_pending(env):
    person = await employee(env)
    payload = {"name": "기본", "effective_from": "2026-09-01", "is_default": True}
    rule = (await env.client.post("/att/work-rules", json=payload)).json()
    await env.service.record_scan(person["qr_token"])
    new = (
        await env.client.patch(
            "/att/work-rules/" + rule["id"],
            json={**payload, "effective_from": "2026-10-01", "check_in_start": "10:00"},
        )
    ).json()
    response = await env.client.post(
        "/att/work-rules/" + new["id"] + "/rejudge", json={"from": "2026-09-28", "to": "2026-09-28"}
    )
    assert response.status_code == 200
    record = (await env.client.get("/att/attendance")).json()[0]
    assert record["in_at"] is None and record["review_required"][0]["reason"] == "early_hours"


async def test_hooks_run_after_commit_and_failure_does_not_rollback(env):
    person = await employee(env)
    events = []

    async def hook(event):
        events.append((event.employee.id, event.result))
        async with env.repo.transaction("default") as tx:
            assert await tx.get("attendance", f"{person['id']}:2026-09-28")
        raise RuntimeError("notification unavailable")

    env.service.hooks.on_recorded = hook
    result = await env.service.record_scan(person["qr_token"])
    assert result["result"] == "in" and events == [(person["id"], "in")]
    assert len((await env.client.get("/att/attendance")).json()) == 1
