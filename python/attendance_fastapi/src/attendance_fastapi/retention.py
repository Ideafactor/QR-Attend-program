"""Daily host-invoked retention job. Legal holds cover records and raw coordinates."""

import calendar
from datetime import date
from attendance_core import instant, local_day


def subtract_months(day, months):
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


async def purge_expired(service, tenant_id="default"):
    async with service.repository.transaction(tenant_id) as tx:
        settings = await service.settings(tx)
        now = service.now()
        today = local_day(now)
        cutoff = subtract_months(today, settings["location_months"])
        employees = {e["id"]: e for e in await tx.list("employees")}
        counts = {
            "employees": 0,
            "records": 0,
            "locations": 0,
            "invites": 0,
            "audit_logs": 0,
            "rule_versions": 0,
        }
        purged = set()
        targets = set()
        for employee in employees.values():
            if employee.get("legal_hold") or not employee.get("exited_at"):
                continue
            exited = date.fromisoformat(employee["exited_at"])
            if exited > subtract_months(today, settings["records_years_after_exit"] * 12):
                continue
            eid = employee["id"]
            purged.add(eid)
            targets.add(eid)
            for table in (
                "attendance",
                "scans",
                "mobile_devices",
                "mobile_invites",
                "memberships",
                "scan_overrides",
                "qr_uses",
                "scan_resolutions",
            ):
                for row in await tx.list(table):
                    if row.get("employee_id") == eid:
                        key = eid if table == "scan_overrides" else row["id"]
                        targets.add(row["id"])
                        await tx.delete(table, key)
                        counts["records"] += 1
            for row in await tx.list("assignments"):
                if row["kind"] in ("employee", "exception") and row["target_id"] == eid:
                    targets.add(row["id"])
                    await tx.delete("assignments", row["id"])
            await tx.delete("employees", eid)
            counts["employees"] += 1
        for scan in await tx.list("scans"):
            employee = employees.get(scan["employee_id"], {})
            if not employee.get("legal_hold") and local_day(instant(scan["scanned_at"])) <= cutoff:
                if any(scan.get(k) is not None for k in ("lat", "lng", "accuracy_m")):
                    scan = {**scan, "lat": None, "lng": None, "accuracy_m": None}
                    await tx.put("scans", scan["id"], scan)
                    counts["locations"] += 1
        for invite in await tx.list("mobile_invites"):
            if employees.get(invite["employee_id"], {}).get("legal_hold"):
                continue
            end = instant(invite.get("used_at") or invite["expires_at"])
            if (now - end).days >= settings["invite_days"]:
                await tx.delete("mobile_invites", invite["id"])
                targets.add(invite["id"])
                counts["invites"] += 1
        for audit in await tx.list("audit_logs"):
            if audit["target_id"] in targets:
                await tx.delete("audit_logs", audit["id"])
                counts["audit_logs"] += 1
                continue
            # Approval audit snapshots also contain original GPS; redact those on schedule.
            if audit["target_table"] == "scans":
                changed = False
                for side in ("before", "after"):
                    snapshot = audit.get(side)
                    if (
                        snapshot
                        and not employees.get(snapshot.get("employee_id"), {}).get("legal_hold")
                        and local_day(instant(snapshot["scanned_at"])) <= cutoff
                    ):
                        audit[side] = {**snapshot, "lat": None, "lng": None, "accuracy_m": None}
                        changed = True
                if changed:
                    await tx.put("audit_logs", audit["id"], audit)
        # Keep rule versions referenced by records, raw scans, audit history,
        # any assignment, or present/future configuration. Remove only obsolete,
        # unreferenced versions and their own configuration audit entries.
        versions = await tx.list("work_rules")
        referenced = {
            r.get("rule_id") for table in ("scans", "attendance") for r in await tx.list(table)
        }
        for audit in await tx.list("audit_logs"):
            if audit["target_table"] in ("scans", "attendance"):
                referenced.update(
                    (audit.get(side) or {}).get("rule_id") for side in ("before", "after")
                )
        assigned_groups = {a["rule_id"] for a in await tx.list("assignments")}
        latest = {}
        for rule in sorted(versions, key=lambda r: (r["effective_from"], r["created_at"])):
            latest[rule["group_id"]] = rule["id"]
        removed_rules = set()
        for rule in versions:
            if (
                rule["id"] in referenced
                or rule["group_id"] in assigned_groups
                or rule["id"] == latest[rule["group_id"]]
                or rule["effective_from"] >= today.isoformat()
            ):
                continue
            await tx.delete("work_rules", rule["id"])
            removed_rules.add(rule["id"])
            counts["rule_versions"] += 1
        for audit in await tx.list("audit_logs"):
            if audit["target_table"] == "work_rules" and audit["target_id"] in removed_rules:
                await tx.delete("audit_logs", audit["id"])
                counts["audit_logs"] += 1
        await service.audit(
            tx,
            "retention",
            "retention",
            today.isoformat(),
            None,
            {
                "counts": counts,
                "policy": settings,
                "employee_ids": sorted(purged),
                "location_cutoff": cutoff.isoformat(),
            },
        )
        return counts
