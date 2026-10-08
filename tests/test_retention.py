from datetime import datetime
from attendance_fastapi.retention import purge_expired


async def test_location_redaction_hold_and_retirement(env):
    for eid, hold in (("expired", False), ("held", True), ("active", False)):
        async with env.repo.transaction("default") as tx:
            await tx.put(
                "employees",
                eid,
                {
                    "id": eid,
                    "name": eid,
                    "active": eid == "active",
                    "exited_at": None if eid == "active" else "2023-09-28",
                    "legal_hold": hold,
                },
            )
            await tx.put(
                "scans",
                eid,
                {
                    "id": eid,
                    "employee_id": eid,
                    "scanned_at": "2026-01-01T00:00:00+00:00",
                    "lat": 37,
                    "lng": 127,
                    "accuracy_m": 5,
                    "distance_m": 10,
                    "result": "in",
                },
            )
    env.clock.value = datetime.fromisoformat("2026-09-28T12:00:00+09:00")
    counts = await purge_expired(env.service)
    assert counts["employees"] == 1 and counts["locations"] == 1
    async with env.repo.transaction("default") as tx:
        assert await tx.get("employees", "expired") is None
        assert (await tx.get("scans", "held"))["lat"] == 37
        active = await tx.get("scans", "active")
        assert active["lat"] is None and active["distance_m"] == 10


async def test_invite_audit_and_unreferenced_old_rule_are_purged(env):
    async with env.repo.transaction("default") as tx:
        await tx.put(
            "employees", "person", {"id": "person", "legal_hold": False, "exited_at": None}
        )
        await tx.put(
            "mobile_invites",
            "invite",
            {
                "id": "invite",
                "employee_id": "person",
                "code_hash": "hashed",
                "used_at": "2026-01-01T00:00:00+00:00",
                "expires_at": "2026-01-02T00:00:00+00:00",
            },
        )
        await env.service.audit(
            tx, "admin", "mobile_invites", "invite", None, {"code_hash": "hashed"}
        )
        for key, day in [("old", "2026-01-01"), ("new", "2026-02-01")]:
            await tx.put(
                "work_rules",
                key,
                {
                    "id": key,
                    "group_id": "group",
                    "effective_from": day,
                    "created_at": day + "T00:00:00+00:00",
                },
            )
    counts = await purge_expired(env.service)
    assert counts["invites"] == 1 and counts["rule_versions"] == 1
    async with env.repo.transaction("default") as tx:
        assert await tx.get("work_rules", "old") is None
        assert await tx.get("work_rules", "new")
        assert not any(a["target_id"] == "invite" for a in await tx.list("audit_logs"))
