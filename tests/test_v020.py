import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import Header, HTTPException

from attendance_core.dynamic_qr import DynamicQrError, issue_dynamic_qr, verify_dynamic_qr
from attendance_fastapi import create_employee_router, create_scanner_router
from attendance_sqlalchemy import SqlTransaction
from tests.test_api import employee, set_time

SECRET = "test-signing-secret-at-least-32-bytes"


def enable(env):
    env.service.config.employee_qr_mode = "rotating"
    env.service.config.qr_signing_secret = SECRET
    env.app.include_router(create_scanner_router(env.service, token=lambda: "scanner"))


async def qr(env, person):
    return (await env.service.issue_employee_qr(person["id"]))["code"]


async def scan(env, code):
    return await env.client.post(
        "/scanner/scans", headers={"Authorization": "Bearer scanner"}, json={"code": code}
    )


def test_qr_window_signature_and_tenant():
    now = datetime.fromisoformat("2026-10-01T09:00:00+09:00")
    qr = issue_dynamic_qr("employee", SECRET, now, tenant_id="company")
    assert (
        issue_dynamic_qr("employee", SECRET, now + timedelta(seconds=59), tenant_id="company") == qr
    )
    assert verify_dynamic_qr(qr.token, SECRET, now, tenant_id="company") == qr
    for value, moment, tenant in [
        (qr.token + "x", now, "company"),
        (qr.token, now, "other"),
        (qr.token, now + timedelta(seconds=60), "company"),
        (qr.token, now - timedelta(microseconds=1), "company"),
        ("aqr2.bad.bad", now, "company"),
        ("😀", now, "company"),
    ]:
        with pytest.raises(DynamicQrError):
            verify_dynamic_qr(value, SECRET, moment, tenant_id=tenant)
    with pytest.raises(ValueError):
        issue_dynamic_qr("employee", "weak", now)


async def test_early_rescan_does_not_mutate_ledger_and_history_is_preserved(env):
    enable(env)
    person = await employee(env)
    first = await scan(env, await qr(env, person))
    assert first.json()["result"] == "in"
    async with env.repo.transaction() as tx:
        saved = await tx.get("attendance", f"{person['id']}:2026-09-28")
        original = await tx.list("scans")
    set_time(env, "2026-09-28T10:00:00")
    code = await qr(env, person)
    rescan = await scan(env, code)
    assert rescan.json()["result"] == "already_in"
    assert rescan.json()["record"]["out_at"] is None
    async with env.repo.transaction() as tx:
        assert await tx.get("attendance", saved["id"]) == saved
        scans = await tx.list("scans")
        assert len(scans) == 2 and original[0] in scans
        stored = str(await tx.list("qr_uses")) + str(scans)
        assert code not in stored
    assert (await scan(env, code)).status_code == 409
    set_time(env, "2026-09-28T18:00:00")
    assert (await scan(env, await qr(env, person))).json()["result"] == "out"
    set_time(env, "2026-09-28T18:10:00")
    latest = await scan(env, await qr(env, person))
    assert latest.json()["record"]["out_at"].startswith("2026-09-28T18:10")


async def test_rotating_dedup_override_and_replay_are_distinct(env):
    enable(env)
    person = await employee(env)
    set_time(env, "2026-09-28T09:00:59")
    assert (await scan(env, await qr(env, person))).json()["result"] == "in"
    response = await env.client.put(
        f"/att/employees/{person['id']}/scan-override",
        json={
            "mode": "out",
            "label": "조퇴",
            "reason": "긴급",
            "expires_at": "2026-09-28T12:00:00+09:00",
        },
    )
    assert response.status_code == 200
    set_time(env, "2026-09-28T09:01:00")
    code = await qr(env, person)
    result = await scan(env, code)
    assert result.json()["result"] == "duplicate" and result.json()["scan_id"]
    assert (await scan(env, code)).status_code == 409
    assert not (await env.client.get(f"/att/employees/{person['id']}/scan-override")).json()[
        "consumed_at"
    ]
    set_time(env, "2026-09-28T09:02:00")
    result = await scan(env, await qr(env, person))
    assert result.json()["result"] == "early_out"
    assert result.json()["record"]["protected"]
    async with env.repo.transaction() as tx:
        assert len(await tx.list("scans")) == 3
        assert len(await tx.list("qr_uses")) == 3


async def test_qr_concurrent_claim_and_rollback(env, monkeypatch):
    enable(env)
    person = await employee(env)
    code = await qr(env, person)
    original = SqlTransaction.put

    async def failing(self, table, key, data):
        if table == "attendance":
            raise RuntimeError("simulated write failure")
        return await original(self, table, key, data)

    with monkeypatch.context() as patch:
        patch.setattr(SqlTransaction, "put", failing)
        with pytest.raises(RuntimeError):
            await env.service.record_scan(code)
    async with env.repo.transaction() as tx:
        assert await tx.list("qr_uses") == [] and await tx.list("scans") == []
    responses = await asyncio.gather(scan(env, code), scan(env, code))
    assert sorted(r.status_code for r in responses) == [200, 409]
    async with env.repo.transaction() as tx:
        assert len(await tx.list("qr_uses")) == 1 and len(await tx.list("scans")) == 1


async def test_qr_expiry_forgery_inactive_and_static_rejection(env):
    enable(env)
    person = await employee(env)
    code = await qr(env, person)
    assert (await scan(env, person["qr_token"])).status_code == 422
    assert (await scan(env, code + "x")).status_code == 422
    set_time(env, "2026-09-28T09:01:00")
    assert (await scan(env, code)).status_code == 410
    code = await qr(env, person)
    await env.client.patch(f"/att/employees/{person['id']}", json={"active": False})
    assert (await scan(env, code)).status_code == 403
    async with env.repo.transaction() as tx:
        assert not await tx.list("qr_uses")


async def test_self_status_auth_since_and_capabilities(env):
    enable(env)
    person = await employee(env)

    def host_employee(authorization: str | None = Header(default=None)):
        if authorization != "Bearer user":
            raise HTTPException(401)
        return person["id"]

    env.app.include_router(create_employee_router(env.service, host_employee))
    assert (await env.client.get("/me/status")).status_code == 401
    headers = {"Authorization": "Bearer user"}
    issued = await env.client.get("/me/qr", headers=headers)
    assert issued.status_code == 200 and issued.headers["cache-control"] == "no-store"
    since = issued.json()["generated_at"]
    status = await env.client.get("/me/status", headers=headers, params={"since": since})
    assert status.json()["attendance"] is None and not status.json()["result_since"]
    await scan(env, issued.json()["code"])
    status = await env.client.get("/me/status", headers=headers, params={"since": since})
    assert status.json()["result_since"] and status.json()["latest_scan"]["result"] == "in"
    assert status.json()["attendance"]["work_mode"] == "OFFICE"
    assert status.json()["attendance"]["scans"][0]["source"] == "kiosk"
    future = "2026-09-28T10:00:00+09:00"
    assert not (
        await env.client.get("/me/status", headers=headers, params={"since": future})
    ).json()["result_since"]
    cap = (
        await env.client.get("/scanner/session", headers={"Authorization": "Bearer scanner"})
    ).json()
    assert (
        cap["transport"] == "USB-COM"
        and cap["qr_interval_seconds"] == 60
        and cap["queue_limit"] == 10
    )


async def test_pending_resolution_does_not_overwrite_raw_scan(env):
    person = await employee(env)
    set_time(env, "2026-09-28T07:00:00")
    result = await env.service.record_scan(person["qr_token"])
    async with env.repo.transaction() as tx:
        raw = await tx.get("scans", result["scan_id"])
    response = await env.client.post(f"/att/pending/{result['scan_id']}/approve", json={"as": "in"})
    assert response.status_code == 200
    async with env.repo.transaction() as tx:
        assert await tx.get("scans", result["scan_id"]) == raw
        assert (await tx.get("scan_resolutions", result["scan_id"]))[
            "pending_status"
        ] == "approved_in"
    assert (await env.client.get("/att/pending")).json() == []
    set_time(env, "2026-09-28T09:00:00")
    subsequent = await env.service.record_scan(person["qr_token"])
    assert subsequent["record"]["scans"][0]["pending_status"] == "approved_in"
    assert (
        await env.client.post(f"/att/pending/{result['scan_id']}/approve", json={"as": "in"})
    ).status_code == 409


@pytest.mark.parametrize("action", ["expire", "cancel"])
async def test_inactive_override_cannot_cause_early_checkout(env, action):
    person = await employee(env)
    await env.service.record_scan(person["qr_token"])
    await env.client.put(
        f"/att/employees/{person['id']}/scan-override",
        json={"label": "조퇴", "reason": "시험", "expires_at": "2026-09-28T10:00:00+09:00"},
    )
    if action == "cancel":
        await env.client.delete(f"/att/employees/{person['id']}/scan-override")
        set_time(env, "2026-09-28T09:30:00")
    else:
        set_time(env, "2026-09-28T10:00:00")
    result = await env.service.record_scan(person["qr_token"])
    assert result["result"] == "already_in" and result["record"]["out_at"] is None


async def test_admin_work_mode_only_uses_accepted_sources(env):
    from tests.test_api import register_mobile

    person = await employee(env)
    await env.service.record_scan(person["qr_token"])
    auth, _ = await register_mobile(env, person)
    site = (
        await env.client.post("/att/sites", json={"name": "현장", "lat": 37, "lng": 127})
    ).json()
    set_time(env, "2026-09-28T10:00:00")
    pending = await env.client.post(
        "/att/mobile/checkins",
        headers={"Authorization": "Bearer " + auth},
        json={"site_token": site["qr_token"], "lat": 38, "lng": 127, "accuracy": 5},
    )
    assert pending.json()["result"] == "pending"
    assert (await env.client.get("/att/attendance")).json()[0]["work_mode"] == "OFFICE"
    set_time(env, "2026-09-28T18:00:00")
    result = await env.client.post(
        "/att/mobile/checkins",
        headers={"Authorization": "Bearer " + auth},
        json={"site_token": site["qr_token"], "lat": 37, "lng": 127, "accuracy": 5},
    )
    assert result.json()["result"] == "out"
    record = (await env.client.get("/att/attendance")).json()[0]
    assert record["work_mode"] == "MIXED"
    assert len(record["scans"]) == 3 and record["scans"][1]["pending_status"] == "pending"
    updated = await env.client.patch(
        f"/att/attendance/{record['id']}", json={"label": "관리자 확인"}
    )
    assert updated.status_code == 200
    assert (await env.client.get("/att/attendance")).json()[0]["work_mode"] == "MANUAL"
