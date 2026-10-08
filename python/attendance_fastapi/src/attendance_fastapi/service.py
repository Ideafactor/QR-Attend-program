import hashlib
import hmac
import inspect
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from attendance_core import (
    UTC,
    Rules,
    DayRecord,
    aware,
    instant,
    local_day,
    judge_scan,
    approve_scan,
    distance_m,
    credited_time,
    expected_out,
)
from attendance_core.repository import AttendanceRepository
from fastapi import HTTPException
from .schemas import SettingsInput
from attendance_core.dynamic_qr import DynamicQrError, issue_dynamic_qr, verify_dynamic_qr

log = logging.getLogger(__name__)


def uid():
    return secrets.token_hex(16)


def token():
    return secrets.token_urlsafe(32)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fail(status, detail):
    raise HTTPException(status, detail)


@dataclass
class AttendanceConfig:
    rules: Rules = field(default_factory=Rules)
    timezone: str = "Asia/Seoul"
    mobile_base_url: str = "/c"
    qr_signing_secret: str | None = field(default=None, repr=False)
    employee_qr_mode: str = "rotating"

    def __post_init__(self):
        if self.employee_qr_mode not in ("rotating", "static"):
            raise ValueError("employee_qr_mode must be rotating or static")
        if self.qr_signing_secret and len(self.qr_signing_secret.encode()) < 32:
            raise ValueError("QR signing secret must contain at least 32 bytes")
        if self.timezone != "Asia/Seoul":
            raise ValueError("only Asia/Seoul is supported")


@dataclass
class Hooks:
    on_recorded: object = None
    on_pending: object = None
    on_approved: object = None


class Attendance:
    def __init__(
        self,
        repository: AttendanceRepository,
        config=None,
        hooks=None,
        tenant_resolver=None,
        clock=None,
    ):
        self.repository = repository
        self.config = config or AttendanceConfig()
        self.hooks = hooks or Hooks()
        self.tenant_resolver = tenant_resolver
        self.clock = clock or (lambda: datetime.now(UTC))
        self.rules = RuleManager(self)

    def now(self):
        return aware(self.clock())

    async def emit(self, name, data):
        hook = getattr(self.hooks, name)
        if hook:
            try:
                result = hook(SimpleNamespace(**data))
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # Commit happened already; a notification failure must not encourage a rescan.
                log.exception("Attendance hook failed: %s", name)

    async def audit(self, tx, actor, table, key, before, after):
        item = dict(
            id=uid(),
            actor_id=actor,
            target_table=table,
            target_id=key,
            before=before,
            after=after,
            created_at=self.now().isoformat(),
        )
        await tx.put("audit_logs", item["id"], item)

    async def require(self, tx, table, key):
        item = await tx.get(table, key)
        if item is None:
            fail(404, f"{table} not found")
        return item

    async def settings(self, tx):
        return await tx.get("settings", "current") or SettingsInput().model_dump()

    async def effective_rule(self, tx, employee_id, day, site_id=None):
        assignments = await tx.list("assignments")
        member = [
            m
            for m in await tx.list("memberships")
            if m["employee_id"] == employee_id
            and m["effective_from"] <= day.isoformat()
            and (not m.get("effective_to") or m["effective_to"] >= day.isoformat())
        ]
        targets = [("exception", employee_id), ("employee", employee_id)]
        if member:
            targets.append(("team", member[0]["team_id"]))
        if site_id:
            targets.append(("site", site_id))
        all_rules = await tx.list("work_rules")
        for kind, target in targets:
            matches = [
                a
                for a in assignments
                if a["kind"] == kind
                and a["target_id"] == target
                and a["effective_from"] <= day.isoformat()
                and (not a.get("effective_to") or a["effective_to"] >= day.isoformat())
            ]
            if matches:
                group = matches[0]["rule_id"]
                choices = [
                    r
                    for r in all_rules
                    if r["group_id"] == group
                    and r["effective_from"] <= day.isoformat()
                    and (not r.get("disabled_at") or local_day(instant(r["disabled_at"])) > day)
                ]
                if not choices:
                    fail(409, "assigned rule has no version for this date")
                if choices:
                    chosen = max(choices, key=lambda r: (r["effective_from"], r["created_at"]))
                    return chosen["id"], Rules(**chosen["values"])
        latest_by_group = {}
        for version in sorted(all_rules, key=lambda r: (r["effective_from"], r["created_at"])):
            if version["effective_from"] <= day.isoformat():
                latest_by_group[version["group_id"]] = version
        defaults = [
            r
            for r in latest_by_group.values()
            if r["is_default"]
            and (not r.get("disabled_at") or local_day(instant(r["disabled_at"])) > day)
        ]
        if defaults:
            chosen = max(defaults, key=lambda r: (r["effective_from"], r["created_at"]))
            return chosen["id"], Rules(**chosen["values"])
        if all_rules:
            fail(409, "no effective rule for this date; assign or create a default rule")
        return None, self.config.rules

    async def save_rule(self, tx, payload, actor, group_id=None):
        key = uid()
        item = dict(
            id=key,
            group_id=group_id or key,
            name=payload.name,
            effective_from=payload.effective_from.isoformat(),
            is_default=payload.is_default,
            values=payload.rule_values(),
            created_at=self.now().isoformat(),
            created_by=actor,
        )
        for old in await tx.list("work_rules"):
            if old["effective_from"] == item["effective_from"] and (
                old["group_id"] == item["group_id"] or old["is_default"] and item["is_default"]
            ):
                fail(409, "a rule version already starts on this date")
        await tx.put("work_rules", key, item)
        await self.audit(tx, actor, "work_rules", key, None, item)
        return item

    async def seed_rules(self, payload, tenant_id="default"):
        async with self.repository.transaction(tenant_id) as tx:
            if await tx.list("work_rules"):
                return False
            await self.save_rule(tx, payload, "initial-config")
            return True

    async def set_assignment(self, tx, kind, target, payload, actor):
        rule = await self.require(tx, "work_rules", payload.rule_id) if payload.rule_id else None
        start = payload.effective_from.isoformat()
        end = payload.effective_to.isoformat() if payload.effective_to else None
        if rule and rule.get("disabled_at"):
            fail(409, "rule is disabled")
        # A null rule closes an assignment from the requested date onward,
        # retaining the interval before that date for historical queries.
        for old in await tx.list("assignments"):
            if old["kind"] != kind or old["target_id"] != target:
                continue
            overlaps = (not old.get("effective_to") or old["effective_to"] >= start) and (
                not end or old["effective_from"] <= end
            )
            if not overlaps:
                continue
            if rule:
                fail(409, "assignment periods overlap; close the prior assignment first")
            if end:
                fail(422, "unassignment must be open-ended")
            if old["effective_from"] >= start:
                await tx.delete("assignments", old["id"])
                await self.audit(tx, actor, "assignments", old["id"], old, None)
            else:
                closed = {
                    **old,
                    "effective_to": (payload.effective_from - timedelta(days=1)).isoformat(),
                }
                await tx.put("assignments", old["id"], closed)
                await self.audit(tx, actor, "assignments", old["id"], old, closed)
        if not rule:
            return None
        versions = [
            r
            for r in await tx.list("work_rules")
            if r["group_id"] == rule["group_id"] and r["effective_from"] <= start
        ]
        if not versions:
            fail(422, "rule starts after assignment")
        item = dict(
            id=uid(),
            kind=kind,
            target_id=target,
            rule_id=rule["group_id"],
            effective_from=start,
            effective_to=end,
        )
        await tx.put("assignments", item["id"], item)
        await self.audit(tx, actor, "assignments", item["id"], None, item)
        return item

    async def active_override(self, tx, employee_id, now):
        item = await tx.get("scan_overrides", employee_id)
        if not item or item.get("consumed_at") or item.get("cancelled_at"):
            return None
        if instant(item["expires_at"]) <= now:
            if not item.get("expired_at"):
                expired = {**item, "expired_at": now.isoformat()}
                await tx.put("scan_overrides", employee_id, expired)
                await self.audit(tx, "system", "scan_overrides", employee_id, item, expired)
            return None
        return item

    async def mobile_device(self, tx, bearer):
        devices = [
            d
            for d in await tx.list("mobile_devices")
            if hmac.compare_digest(d["token_hash"], digest(bearer))
        ]
        if not devices:
            fail(401, "invalid mobile token")
        device = devices[0]
        if device.get("revoked_at"):
            fail(403, "device revoked")
        if instant(device["expires_at"]) <= self.now():
            fail(401, "token expired")
        employee = await self.require(tx, "employees", device["employee_id"])
        if not employee["active"]:
            fail(403, "employee inactive")
        return device, employee

    async def resolve_site(self, tx, site_token):
        if "." in site_token:
            parts = site_token.split(".")
            if len(parts) != 3:
                fail(401, "invalid site token")
            key, stamp, signature = parts
            site = await self.require(tx, "sites", key)
            if site["qr_mode"] != "rotating":
                fail(401, "invalid site mode")
            expected = hmac.new(
                site["qr_secret"].encode(), f"{key}.{stamp}".encode(), "sha256"
            ).hexdigest()
            if not stamp.isdigit() or not hmac.compare_digest(signature, expected):
                fail(401, "invalid site token")
            if int(stamp) != int(self.now().timestamp()) // 30:
                fail(410, "qr_expired")
        else:
            sites = [
                s
                for s in await tx.list("sites")
                if s["qr_mode"] == "static"
                and hmac.compare_digest(s["qr_hash"], digest(site_token))
            ]
            if not sites:
                fail(404, "site QR not found")
            site = sites[0]
        if not site["active"]:
            fail(403, "site_inactive")
        return site

    def qr_secret(self):
        if not self.config.qr_signing_secret:
            fail(503, "ATTENDANCE_QR_NOT_CONFIGURED")
        return self.config.qr_signing_secret

    async def issue_employee_qr(self, employee_id, *, tenant_id="default"):
        async with self.repository.transaction(tenant_id) as tx:
            employee = await self.require(tx, "employees", employee_id)
            if not employee["active"]:
                fail(403, "ATTENDANCE_EMPLOYEE_INACTIVE")
            now = self.now()
            qr = issue_dynamic_qr(employee_id, self.qr_secret(), now, tenant_id=tenant_id)
            return dict(
                code=qr.token,
                issued_at=qr.issued_at.isoformat(),
                expires_at=qr.expires_at.isoformat(),
                generated_at=now.isoformat(),
                server_time=now.isoformat(),
                interval_seconds=60,
            )

    async def projected_scans(self, tx):
        resolutions = {r["id"]: r for r in await tx.list("scan_resolutions")}
        return [
            {
                **s,
                **{
                    k: v
                    for k, v in resolutions.get(s["id"], {}).items()
                    if k in ("pending_status", "processed_at", "processed_by", "work_date")
                },
            }
            for s in await tx.list("scans")
        ]

    def project_record(self, record, scans):
        relevant = sorted(
            [
                s
                for s in scans
                if s["employee_id"] == record["employee_id"]
                and s.get("work_date", local_day(instant(s["scanned_at"])).isoformat())
                == record["work_date"]
            ],
            key=lambda s: (instant(s["scanned_at"]), s.get("sequence", 0), s["id"]),
        )
        # Work mode describes the ledger's accepted directions, not rejected/pending attempts.
        sources = {record.get("in_source"), record.get("out_source")} - {None}
        mode = (
            "MANUAL"
            if record.get("in_kind") == "manual" or record.get("out_kind") == "manual"
            else "MIXED"
            if sources == {"kiosk", "mobile"}
            else "EXTERNAL"
            if sources == {"mobile"}
            else "OFFICE"
            if sources
            else "MANUAL"
        )
        return {**record, "work_mode": mode, "scans": [self.scan_summary(s) for s in relevant]}

    @staticmethod
    def scan_summary(scan):
        return {
            key: scan.get(key)
            for key in (
                "id",
                "employee_id",
                "scanned_at",
                "source",
                "result",
                "pending_status",
                "pending_reason",
            )
        }

    async def get_employee_status(self, employee_id, *, tenant_id="default", since=None):
        async with self.repository.transaction(tenant_id) as tx:
            employee = await self.require(tx, "employees", employee_id)
            if not employee["active"]:
                fail(403, "ATTENDANCE_EMPLOYEE_INACTIVE")
            now = self.now()
            day = local_day(now)
            scans = [
                s
                for s in await self.projected_scans(tx)
                if s["employee_id"] == employee_id and local_day(instant(s["scanned_at"])) == day
            ]
            latest = max(
                scans,
                key=lambda s: (instant(s["scanned_at"]), s.get("sequence", 0), s["id"]),
                default=None,
            )
            saved = await tx.get("attendance", f"{employee_id}:{day}")
            return dict(
                employee_id=employee_id,
                work_date=day.isoformat(),
                server_time=now.isoformat(),
                attendance=self.project_record(saved, scans) if saved else None,
                latest_scan=self.scan_summary(latest) if latest else None,
                result_since=bool(
                    latest and since is not None and instant(latest["scanned_at"]) >= aware(since)
                ),
            )

    async def record_scan(
        self,
        code=None,
        source="kiosk",
        *,
        tenant_id="default",
        mobile_token=None,
        site_token=None,
        lat=None,
        lng=None,
        accuracy=None,
    ):
        if source not in ("kiosk", "mobile"):
            raise ValueError("invalid source")
        async with self.repository.transaction(tenant_id) as tx:
            # Capture server time after acquiring the lock, so concurrent scans are ordered.
            now = self.now()
            site, location_reason, distance, rotating_qr = None, None, None, None
            if source == "mobile":
                _, employee = await self.mobile_device(tx, mobile_token or "")
                site = await self.resolve_site(tx, site_token or "")
                distance = distance_m(lat, lng, site["lat"], site["lng"])
                settings = await self.settings(tx)
                if accuracy is None or accuracy < 0:
                    fail(422, "accuracy required")
                if accuracy > settings["max_accuracy_m"]:
                    location_reason = "low_accuracy"
                elif distance > site["radius_m"]:
                    location_reason = "outside_geofence"
            elif self.config.employee_qr_mode == "rotating":
                try:
                    rotating_qr = verify_dynamic_qr(
                        code or "", self.qr_secret(), now, tenant_id=tenant_id
                    )
                except DynamicQrError as error:
                    fail(410 if error.code == "ATTENDANCE_QR_EXPIRED" else 422, error.code)
                if await tx.get("qr_uses", rotating_qr.token_hash):
                    fail(409, "ATTENDANCE_QR_ALREADY_USED")
                employee = await self.require(tx, "employees", rotating_qr.employee_id)
                if not employee["active"]:
                    fail(403, "ATTENDANCE_EMPLOYEE_INACTIVE")
            else:
                candidates = [
                    e
                    for e in await tx.list("employees")
                    if hmac.compare_digest(e["qr_hash"], digest(code or ""))
                ]
                if not candidates:
                    fail(404, "employee QR not found")
                employee = candidates[0]
                if not employee["active"]:
                    fail(403, "employee inactive")
            day = local_day(now)
            record_key = f"{employee['id']}:{day}"
            saved = await tx.get("attendance", record_key)
            if saved:
                rule_id, rules = saved.get("rule_id"), Rules(**saved["rule_snapshot"])
            else:
                rule_id, rules = await self.effective_rule(
                    tx, employee["id"], day, site["id"] if site else None
                )
            scans = [
                s for s in await self.projected_scans(tx) if s["employee_id"] == employee["id"]
            ]
            last_scan = max(
                (instant(s["scanned_at"]) for s in scans if s["result"] != "duplicate"),
                default=None,
            )
            override = await self.active_override(tx, employee["id"], now)
            decision = judge_scan(
                now,
                DayRecord.from_dict(saved) if saved else None,
                rules,
                last_scan=last_scan,
                pending_reason=location_reason,
                force_out=override is not None,
            )
            result = dict(
                result=decision.kind,
                employee_name=employee["name"],
                employee_id=employee["id"],
                site_name=site["name"] if site else None,
                recorded_at=now.isoformat(),
                pending_reason=decision.pending_reason,
                distance_m=distance,
                radius_m=site["radius_m"] if site else None,
            )
            if decision.kind != "duplicate" and override and saved and saved.get("protected"):
                fail(409, "record protected; edit attendance explicitly")
            scan = dict(
                id=uid(),
                sequence=1 + max((s.get("sequence", 0) for s in scans), default=0),
                employee_id=employee["id"],
                scanned_at=now.isoformat(),
                source=source,
                site_id=site["id"] if site else None,
                lat=lat,
                lng=lng,
                accuracy_m=accuracy,
                distance_m=distance,
                result=decision.kind,
                pending_reason=decision.pending_reason,
                pending_status="pending" if decision.kind == "pending" else None,
                rule_id=rule_id,
                rule_snapshot=rules.snapshot(),
                override_id=override["id"]
                if override and decision.kind not in ("duplicate", "already_in")
                else None,
                override_label=override["label"]
                if override and decision.kind not in ("duplicate", "already_in")
                else None,
            )
            await tx.put("scans", scan["id"], scan)
            result["scan_id"] = scan["id"]
            if rotating_qr:
                await tx.put(
                    "qr_uses",
                    rotating_qr.token_hash,
                    dict(
                        id=rotating_qr.token_hash,
                        employee_id=employee["id"],
                        issued_at=rotating_qr.issued_at.isoformat(),
                        expires_at=rotating_qr.expires_at.isoformat(),
                        consumed_at=now.isoformat(),
                        scan_id=scan["id"],
                    ),
                )
            if override and scan["override_id"]:
                consumed = {
                    **override,
                    "consumed_at": now.isoformat(),
                    "consumed_scan_id": scan["id"],
                }
                await tx.put("scan_overrides", employee["id"], consumed)
                await self.audit(
                    tx, override["created_by"], "scan_overrides", employee["id"], override, consumed
                )
            if decision.record and decision.kind not in (
                "pending",
                "protected",
                "duplicate",
                "already_in",
            ):
                item = {
                    **(saved or {}),
                    **decision.record.to_dict(),
                    "id": record_key,
                    "employee_id": employee["id"],
                    "rule_id": rule_id,
                    "rule_snapshot": rules.snapshot(),
                    "updated_at": now.isoformat(),
                }
                direction = "in" if decision.kind in ("in", "late_in", "tardy_in") else "out"
                item.update(
                    {direction + "_source": source, direction + "_site_id": scan["site_id"]}
                )
                if override:
                    item.update(label=override["label"], updated_by=override["created_by"])
                    await self.audit(
                        tx, override["created_by"], "attendance", record_key, saved, item
                    )
                await tx.put("attendance", record_key, item)
                result["record"] = self.project_record(item, [*scans, scan])
            elif saved:
                result["record"] = self.project_record(saved, [*scans, scan])
        await self.emit(
            "on_pending" if result["result"] == "pending" else "on_recorded",
            {
                **result,
                "employee": SimpleNamespace(
                    id=employee["id"],
                    name=employee["name"],
                    host_user_id=employee.get("host_user_id"),
                ),
            },
        )
        return result

    async def approve(self, tx, scan_id, action, actor):
        scan = await self.require(tx, "scans", scan_id)
        if await tx.get("scan_resolutions", scan_id):
            fail(409, "scan already processed or not pending")
        if scan.get("pending_status") != "pending":
            fail(409, "scan already processed or not pending")
        if scan.get("override_id") and action not in ("out", "dismiss"):
            fail(409, "override scan requires same-day checkout approval")
        saved_scan = dict(scan)
        if action != "dismiss":
            scanned = instant(scan["scanned_at"])
            day = local_day(scanned) - timedelta(days=action == "prev_out")
            key = f"{scan['employee_id']}:{day}"
            saved = await tx.get("attendance", key)
            if saved:
                rule_id, rules = saved["rule_id"], Rules(**saved["rule_snapshot"])
            elif action == "prev_out":
                rule_id, rules = await self.effective_rule(
                    tx, scan["employee_id"], day, scan["site_id"]
                )
            else:
                rule_id, rules = scan["rule_id"], Rules(**scan["rule_snapshot"])
            try:
                record = approve_scan(
                    scanned, DayRecord.from_dict(saved) if saved else None, rules, action
                )
            except ValueError as error:
                fail(409, str(error))
            item = {
                **(saved or {}),
                **record.to_dict(),
                "id": key,
                "employee_id": scan["employee_id"],
                "rule_id": rule_id,
                "rule_snapshot": rules.snapshot(),
                "updated_by": actor,
                "updated_at": self.now().isoformat(),
            }
            direction = "in" if action == "in" else "out"
            item.update(
                {direction + "_source": scan["source"], direction + "_site_id": scan["site_id"]}
            )
            if scan.get("override_id"):
                item["label"] = scan["override_label"]
            await tx.put("attendance", key, item)
            await self.audit(tx, actor, "attendance", key, saved, item)
        scan = {
            **scan,
            "pending_status": "dismissed" if action == "dismiss" else "approved_" + action,
            "processed_by": actor,
            "processed_at": self.now().isoformat(),
        }
        await tx.put(
            "scan_resolutions",
            scan_id,
            {
                "id": scan_id,
                "employee_id": scan["employee_id"],
                "pending_status": scan["pending_status"],
                "processed_by": actor,
                "processed_at": scan["processed_at"],
                "work_date": (
                    local_day(instant(scan["scanned_at"])) - timedelta(days=action == "prev_out")
                ).isoformat(),
            },
        )
        await self.audit(tx, actor, "scans", scan_id, saved_scan, scan)
        return scan

    async def manual_record(self, tx, employee_id, day, changes, actor, key=None):
        await self.require(tx, "employees", employee_id)
        key = key or f"{employee_id}:{day}"
        saved = await tx.get("attendance", key)
        if saved:
            rule_id, rules = saved["rule_id"], Rules(**saved["rule_snapshot"])
        else:
            rule_id, rules = await self.effective_rule(tx, employee_id, day)
        base = {**(saved or DayRecord(day).to_dict()), **changes}
        arrival, departure = instant(base.get("in_at")), instant(base.get("out_at"))
        if arrival and local_day(arrival) != day:
            fail(422, "check-in must belong to work date")
        if departure and arrival and departure <= arrival:
            fail(422, "checkout must be after check-in")
        if departure and local_day(departure) not in (day, day + timedelta(days=1)):
            fail(422, "checkout must be on work date or the following date")
        credited = (credited_time(arrival, rules) or arrival) if arrival else None
        try:
            expected = expected_out(credited, rules).isoformat() if credited else None
        except ValueError as error:
            fail(422, str(error))
        # Normalize stored instants to UTC even when an administrator supplied +09:00.
        base.update(
            in_at=arrival.isoformat() if arrival else None,
            out_at=departure.isoformat() if departure else None,
        )
        base.update(
            id=key,
            employee_id=employee_id,
            work_date=day.isoformat(),
            credited_in_at=credited.isoformat() if credited else None,
            expected_out_at=expected,
            in_kind="manual" if arrival else None,
            out_kind="manual" if departure else None,
            protected=True,
            rule_id=rule_id,
            rule_snapshot=rules.snapshot(),
            updated_by=actor,
            updated_at=self.now().isoformat(),
        )
        await tx.put("attendance", key, base)
        await self.audit(tx, actor, "attendance", key, saved, base)
        return base

    def router(self, admin_dependency):
        from .routes import build_router

        return build_router(self, admin_dependency)


def create_attendance(repository, config=None, hooks=None, tenant_resolver=None, clock=None):
    return Attendance(repository, config, hooks, tenant_resolver, clock)


class RuleManager:
    def __init__(self, attendance):
        self.attendance = attendance

    async def create(self, *, tenant_id="default", actor_id="host", **values):
        from .schemas import RuleInput

        payload = RuleInput(**values)
        async with self.attendance.repository.transaction(tenant_id) as tx:
            return await self.attendance.save_rule(tx, payload, actor_id)
