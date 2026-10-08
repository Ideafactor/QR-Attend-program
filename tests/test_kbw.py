from examples.kbw import scanner_router
from tests.test_api import employee


async def test_scanner_auth_and_recording(env):
    env.app.include_router(scanner_router(env.service, token=lambda: "scanner-only"))
    person = await employee(env)
    url = "/api/scanner/scans"
    body = {"code": person["qr_token"]}
    assert (await env.client.post(url, json=body)).status_code == 401
    headers = {"Authorization": "Bearer scanner-only"}
    result = await env.client.post(url, headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["result"] == "in"
    assert result.headers["cache-control"] == "no-store"
    assert person["qr_token"] not in result.text
    assert (await env.client.post(url, headers=headers, json=body)).json()["result"] == "duplicate"
    for extra in ({"tenant_id": "other"}, {"source": "mobile"}, {"recorded_at": "2020-01-01"}):
        assert (await env.client.post(url, headers=headers, json=body | extra)).status_code == 422
    assert (
        await env.client.post(url, headers=headers, json={"code": "unknown"})
    ).status_code == 404
    assert (
        await env.client.post(url, headers=headers, json={"code": "x" * 1025})
    ).status_code == 422
    assert (
        await env.client.get("/att/employees", headers={**headers, "X-Admin": ""})
    ).status_code in (401, 403)


async def test_scanner_disabled_and_tenant_bound(env):
    env.app.include_router(scanner_router(env.service, token=lambda: None))
    assert (await env.client.get("/api/scanner/session")).status_code == 503


async def test_scanner_ignores_client_tenant(env):
    env.app.include_router(
        scanner_router(env.service, token=lambda: "scanner", tenant_id="default")
    )
    person = await employee(env)
    result = await env.client.post(
        "/api/scanner/scans",
        headers={"Authorization": "Bearer scanner", "X-Tenant": "other"},
        json={"code": person["qr_token"]},
    )
    assert result.status_code == 200
    assert result.json()["employee_name"] == person["name"]


async def test_packaged_scanner_custom_prefix(env):
    from attendance_fastapi import create_scanner_router

    env.app.include_router(
        create_scanner_router(env.service, token=lambda: "custom", prefix="/api/v1/clock")
    )
    person = await employee(env)
    result = await env.client.post(
        "/api/v1/clock/scans",
        headers={"Authorization": "Bearer custom"},
        json={"code": person["qr_token"]},
    )
    assert result.status_code == 200
    assert result.json()["result"] == "in"
    assert (await env.client.get("/api/scanner/session")).status_code == 404
