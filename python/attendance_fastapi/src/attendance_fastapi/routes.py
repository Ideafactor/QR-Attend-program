import csv
import hmac
import inspect
import io
from datetime import date, timedelta
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response
from attendance_core import SEOUL, instant, local_day, Rules, DayRecord, judge_scan
from .schemas import (
    RuleInput,
    EmployeeInput,
    EmployeePatch,
    AssignmentInput,
    ExceptionInput,
    OverrideInput,
    ApproveInput,
    ManualInput,
    AttendancePatch,
    RejudgeInput,
    SiteInput,
    RegisterInput,
    MobileCheckIn,
    DeviceInput,
    DeviceRegisterInput,
    SettingsInput,
)
from .service import uid, token, digest, fail
from .schemas import (
    AttendanceOutput,
    CheckResultOutput,
    MobileConfigOutput,
    SiteInfoOutput,
    MobileMeOutput,
    EmployeeQrOutput,
)


def public(value):
    if isinstance(value, dict):
        return {
            k: public(v)
            for k, v in value.items()
            if k not in ("qr_hash", "qr_secret", "token_hash", "code_hash")
        }
    if isinstance(value, list):
        return [public(v) for v in value]
    if isinstance(value, str) and "T" in value:
        try:
            return instant(value).astimezone(SEOUL).isoformat()
        except (ValueError, TypeError):
            pass
    return value


def svg(value):
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    return Response(buffer.getvalue(), media_type="image/svg+xml")


def build_router(service, admin_dependency):
    router = APIRouter()

    async def tenant(request: Request):
        if not service.tenant_resolver:
            return "default"
        value = service.tenant_resolver(request)
        if inspect.isawaitable(value):
            value = await value
        if not isinstance(value, str) or not value or len(value) > 128:
            fail(403, "tenant required")
        return value

    async def admin(actor=Depends(admin_dependency)):
        if actor is None or actor is False:
            fail(403, "admin required")
        return str(actor)

    def bearer(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith("Bearer "):
            fail(401, "bearer token required")
        return authorization[7:]

    @router.get("/employees/{employee_id}/qr", response_model=EmployeeQrOutput)
    async def issue_employee_qr(
        employee_id: str, response: Response, t=Depends(tenant), actor=Depends(admin)
    ):
        response.headers["Cache-Control"] = "no-store"
        return public(await service.issue_employee_qr(employee_id, tenant_id=t))

    @router.get("/employees")
    async def employees(t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            return public(await tx.list("employees"))

    @router.post("/employees", status_code=201)
    async def employee_create(payload: EmployeeInput, t=Depends(tenant), actor=Depends(admin)):
        code = token()
        item = dict(
            id=uid(),
            **payload.model_dump(),
            qr_hash=digest(code),
            active=True,
            exited_at=None,
            legal_hold=False,
            created_at=service.now().isoformat(),
        )
        async with service.repository.transaction(t) as tx:
            await tx.put("employees", item["id"], item)
            await service.audit(tx, actor, "employees", item["id"], None, item)
        return {**public(item), "qr_token": code}

    @router.patch("/employees/{employee_id}")
    async def employee_patch(
        employee_id: str, payload: EmployeePatch, t=Depends(tenant), actor=Depends(admin)
    ):
        changes = payload.model_dump(mode="json", exclude_unset=True)
        if any(changes.get(k) is None for k in ("name", "active", "legal_hold") if k in changes):
            fail(422, "name, active and legal_hold cannot be null")
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "employees", employee_id)
            item = {**old, **changes}
            await tx.put("employees", employee_id, item)
            await service.audit(tx, actor, "employees", employee_id, old, item)
            return public(item)

    @router.post("/employees/{employee_id}/reissue-qr")
    async def employee_qr(employee_id: str, t=Depends(tenant), actor=Depends(admin)):
        code = token()
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "employees", employee_id)
            item = {**old, "qr_hash": digest(code)}
            await tx.put("employees", employee_id, item)
            await service.audit(tx, actor, "employees", employee_id, old, item)
        return {"qr_token": code}

    @router.post("/qr/render")
    async def render_qr(payload: DeviceRegisterInput, actor=Depends(admin)):
        # Hash-only storage: render the token returned at issuance; never retrieve plaintext.
        return svg(payload.code)

    @router.get("/work-rules")
    async def rules(t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            return public(await tx.list("work_rules"))

    @router.post("/work-rules", status_code=201)
    async def rule_create(payload: RuleInput, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            return public(await service.save_rule(tx, payload, actor))

    @router.patch("/work-rules/{rule_id}")
    async def rule_patch(rule_id: str, payload: RuleInput, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "work_rules", rule_id)
            return public(await service.save_rule(tx, payload, actor, old["group_id"]))

    @router.delete("/work-rules/{rule_id}")
    async def rule_delete(rule_id: str, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "work_rules", rule_id)
            if old["is_default"] or any(
                a["rule_id"] == old["group_id"] for a in await tx.list("assignments")
            ):
                fail(409, "rule is assigned")
            item = {**old, "disabled_at": service.now().isoformat()}
            await tx.put("work_rules", rule_id, item)
            await service.audit(tx, actor, "work_rules", rule_id, old, item)
            return public(item)

    @router.put("/employees/{employee_id}/work-rule")
    async def employee_rule(
        employee_id: str, payload: AssignmentInput, t=Depends(tenant), actor=Depends(admin)
    ):
        async with service.repository.transaction(t) as tx:
            await service.require(tx, "employees", employee_id)
            return await service.set_assignment(tx, "employee", employee_id, payload, actor)

    @router.put("/sites/{site_id}/work-rule")
    async def site_rule(
        site_id: str, payload: AssignmentInput, t=Depends(tenant), actor=Depends(admin)
    ):
        async with service.repository.transaction(t) as tx:
            await service.require(tx, "sites", site_id)
            return await service.set_assignment(tx, "site", site_id, payload, actor)

    @router.put("/employees/{employee_id}/rule-exception")
    async def exception(
        employee_id: str, payload: ExceptionInput, t=Depends(tenant), actor=Depends(admin)
    ):
        async with service.repository.transaction(t) as tx:
            await service.require(tx, "employees", employee_id)
            result = await service.set_assignment(
                tx,
                "exception",
                employee_id,
                AssignmentInput(
                    rule_id=payload.rule_id, effective_from=payload.date, effective_to=payload.date
                ),
                actor,
            )
            result["reason"] = payload.reason
            await tx.put("assignments", result["id"], result)
            return result

    @router.patch("/assignments/{assignment_id}")
    async def close_assignment(
        assignment_id: str, effective_to: date, t=Depends(tenant), actor=Depends(admin)
    ):
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "assignments", assignment_id)
            if effective_to.isoformat() < old["effective_from"] or (
                old.get("effective_to") and effective_to.isoformat() > old["effective_to"]
            ):
                fail(422, "this endpoint only shortens an assignment")
            item = {**old, "effective_to": effective_to.isoformat()}
            await tx.put("assignments", assignment_id, item)
            await service.audit(tx, actor, "assignments", assignment_id, old, item)
            return item

    @router.get("/employees/{employee_id}/effective-rule")
    async def effective(
        employee_id: str,
        date: date,
        site_id: str | None = None,
        t=Depends(tenant),
        actor=Depends(admin),
    ):
        async with service.repository.transaction(t) as tx:
            await service.require(tx, "employees", employee_id)
            key, rule = await service.effective_rule(tx, employee_id, date, site_id)
            return {"rule_id": key, **rule.snapshot()}

    @router.post("/teams", status_code=201)
    async def team_create(payload: EmployeeInput, t=Depends(tenant), actor=Depends(admin)):
        item = {"id": uid(), "name": payload.name}
        async with service.repository.transaction(t) as tx:
            await tx.put("teams", item["id"], item)
            await service.audit(tx, actor, "teams", item["id"], None, item)
        return item

    @router.get("/teams")
    async def teams(t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            return await tx.list("teams")

    @router.put("/teams/{team_id}/work-rule")
    async def team_rule(
        team_id: str, payload: AssignmentInput, t=Depends(tenant), actor=Depends(admin)
    ):
        async with service.repository.transaction(t) as tx:
            await service.require(tx, "teams", team_id)
            return await service.set_assignment(tx, "team", team_id, payload, actor)

    @router.put("/employees/{employee_id}/team/{team_id}")
    async def membership(
        employee_id: str,
        team_id: str,
        effective_from: date,
        effective_to: date | None = None,
        t=Depends(tenant),
        actor=Depends(admin),
    ):
        if effective_to and effective_to < effective_from:
            fail(422, "invalid period")
        async with service.repository.transaction(t) as tx:
            await service.require(tx, "employees", employee_id)
            await service.require(tx, "teams", team_id)
            for old in await tx.list("memberships"):
                if (
                    old["employee_id"] == employee_id
                    and (
                        not old.get("effective_to")
                        or old["effective_to"] >= effective_from.isoformat()
                    )
                    and (not effective_to or old["effective_from"] <= effective_to.isoformat())
                ):
                    fail(409, "membership periods overlap")
            item = dict(
                id=uid(),
                employee_id=employee_id,
                team_id=team_id,
                effective_from=effective_from.isoformat(),
                effective_to=effective_to.isoformat() if effective_to else None,
            )
            await tx.put("memberships", item["id"], item)
            await service.audit(tx, actor, "memberships", item["id"], None, item)
            return item

    @router.put("/employees/{employee_id}/scan-override")
    async def override(
        employee_id: str, payload: OverrideInput, t=Depends(tenant), actor=Depends(admin)
    ):
        async with service.repository.transaction(t) as tx:
            employee = await service.require(tx, "employees", employee_id)
            if not employee["active"]:
                fail(403, "employee inactive")
            if payload.expires_at <= service.now():
                fail(422, "expiry must be in the future")
            if await service.active_override(tx, employee_id, service.now()):
                fail(409, "cancel the existing override first")
            item = dict(
                id=uid(),
                employee_id=employee_id,
                **payload.model_dump(mode="json"),
                created_by=actor,
                created_at=service.now().isoformat(),
                consumed_at=None,
                cancelled_at=None,
            )
            await tx.put("scan_overrides", employee_id, item)
            await service.audit(tx, actor, "scan_overrides", employee_id, None, item)
            return public(item)

    @router.get("/employees/{employee_id}/scan-override")
    async def override_get(employee_id: str, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            await service.require(tx, "employees", employee_id)
            await service.active_override(tx, employee_id, service.now())
            return public(await tx.get("scan_overrides", employee_id))

    @router.delete("/employees/{employee_id}/scan-override")
    async def override_cancel(employee_id: str, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "scan_overrides", employee_id)
            if old.get("consumed_at"):
                fail(409, "override already consumed")
            item = {**old, "cancelled_at": service.now().isoformat()}
            await tx.put("scan_overrides", employee_id, item)
            await service.audit(tx, actor, "scan_overrides", employee_id, old, item)
            return public(item)

    async def records(tx, day=None, month=None, employee=None):
        if month:
            try:
                date.fromisoformat(month + "-01")
            except ValueError:
                fail(422, "month must be YYYY-MM")
        return [
            r
            for r in await tx.list("attendance")
            if (not day or r["work_date"] == day.isoformat())
            and (not month or r["work_date"].startswith(month + "-"))
            and (not employee or r["employee_id"] == employee)
        ]

    @router.get("/attendance", response_model=list[AttendanceOutput])
    async def attendance(
        date: date | None = None,
        month: str | None = None,
        employee_id: str | None = None,
        t=Depends(tenant),
        actor=Depends(admin),
    ):
        async with service.repository.transaction(t) as tx:
            scans = await service.projected_scans(tx)
            return public(
                [
                    service.project_record(r, scans)
                    for r in await records(tx, date, month, employee_id)
                ]
            )

    @router.post("/attendance", status_code=201)
    async def manual(payload: ManualInput, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            if await tx.get("attendance", f"{payload.employee_id}:{payload.work_date}"):
                fail(409, "record exists; use PATCH")
            return public(
                await service.manual_record(
                    tx,
                    payload.employee_id,
                    payload.work_date,
                    payload.model_dump(mode="json", exclude={"employee_id", "work_date"}),
                    actor,
                )
            )

    @router.patch("/attendance/{record_id}")
    async def manual_patch(
        record_id: str, payload: AttendancePatch, t=Depends(tenant), actor=Depends(admin)
    ):
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "attendance", record_id)
            return public(
                await service.manual_record(
                    tx,
                    old["employee_id"],
                    date.fromisoformat(old["work_date"]),
                    payload.model_dump(mode="json", exclude_unset=True),
                    actor,
                    record_id,
                )
            )

    @router.get("/pending")
    async def pending(t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            return public(
                [
                    s
                    for s in await service.projected_scans(tx)
                    if s.get("pending_status") == "pending"
                ]
            )

    @router.post("/pending/{scan_id}/approve")
    async def approve(scan_id: str, payload: ApproveInput, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            item = await service.approve(tx, scan_id, payload.as_, actor)
        await service.emit("on_approved", item)
        return public(item)

    @router.post("/pending/{scan_id}/dismiss")
    async def dismiss(scan_id: str, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            return public(await service.approve(tx, scan_id, "dismiss", actor))

    @router.post("/work-rules/{rule_id}/rejudge")
    async def rejudge(rule_id: str, payload: RejudgeInput, t=Depends(tenant), actor=Depends(admin)):
        if payload.to < payload.from_ or (payload.to - payload.from_).days > 366:
            fail(422, "period must be between 0 and 366 days")
        count = 0
        async with service.repository.transaction(t) as tx:
            target = await service.require(tx, "work_rules", rule_id)
            rule = Rules(**target["values"])
            scans = await tx.list("scans")
            for saved in await records(tx):
                day = date.fromisoformat(saved["work_date"])
                if saved.get("protected") or not payload.from_ <= day <= payload.to:
                    continue
                selected, _ = await service.effective_rule(
                    tx, saved["employee_id"], day, saved.get("in_site_id")
                )
                selected_rule = await tx.get("work_rules", selected) if selected else None
                if not selected_rule or selected_rule["group_id"] != target["group_id"]:
                    continue
                current = None
                reasons = []
                provenance = {
                    "in_source": None,
                    "in_site_id": None,
                    "out_source": None,
                    "out_site_id": None,
                }
                for scan in sorted(scans, key=lambda s: instant(s["scanned_at"])):
                    if (
                        scan["employee_id"] != saved["employee_id"]
                        or local_day(instant(scan["scanned_at"])) != day
                    ):
                        continue
                    if (
                        scan.get("pending_status")
                        or scan.get("override_id")
                        or scan["result"] == "duplicate"
                    ):
                        continue
                    decision = judge_scan(instant(scan["scanned_at"]), current, rule)
                    current = decision.record
                    if decision.kind == "pending":
                        reasons.append({"scan_id": scan["id"], "reason": decision.pending_reason})
                    elif decision.kind in ("in", "tardy_in", "late_in"):
                        provenance.update(in_source=scan["source"], in_site_id=scan["site_id"])
                    elif decision.kind in ("out", "early_out", "out_no_in"):
                        provenance.update(out_source=scan["source"], out_site_id=scan["site_id"])
                item = {
                    **saved,
                    **(current or DayRecord(day)).to_dict(),
                    **provenance,
                    "rule_id": rule_id,
                    "rule_snapshot": rule.snapshot(),
                    "updated_by": actor,
                    "updated_at": service.now().isoformat(),
                    "review_required": reasons,
                }
                await tx.put("attendance", saved["id"], item)
                await service.audit(tx, actor, "attendance", saved["id"], saved, item)
                count += 1
            return {"updated": count}

    @router.get("/audit-logs")
    async def audit(t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            return public(await tx.list("audit_logs"))

    @router.get("/export")
    async def export(month: str, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            rows = public(await records(tx, month=month))
        fields = [
            "employee_id",
            "work_date",
            "in_at",
            "credited_in_at",
            "expected_out_at",
            "out_at",
            "label",
            "memo",
        ]
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(fields)
        for row in rows:
            values = [str(row.get(k) or "") for k in fields]
            writer.writerow(
                ["'" + v if v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for v in values]
            )
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="attendance.csv"'},
        )

    @router.get("/settings")
    async def settings(t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            return await service.settings(tx)

    @router.put("/settings")
    async def settings_put(payload: SettingsInput, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            old = await service.settings(tx)
            item = payload.model_dump()
            if (
                item["consent_text"] != old["consent_text"]
                or item["location_months"] != old["location_months"]
            ) and item["consent_version"] == old["consent_version"]:
                fail(422, "change consent_version when consent text or location retention changes")
            await tx.put("settings", "current", item)
            await service.audit(tx, actor, "settings", "current", old, item)
            return item

    @router.get("/sites")
    async def sites(t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            return public(await tx.list("sites"))

    @router.post("/sites", status_code=201)
    async def site_create(payload: SiteInput, t=Depends(tenant), actor=Depends(admin)):
        code = token()
        item = dict(id=uid(), **payload.model_dump(), qr_hash=digest(code), qr_secret=token())
        async with service.repository.transaction(t) as tx:
            await tx.put("sites", item["id"], item)
            await service.audit(tx, actor, "sites", item["id"], None, item)
        return {
            **public(item),
            "qr_token": code,
            "check_url": service.config.mobile_base_url
            + "?"
            + urlencode({"site": item["id"], "t": code}),
        }

    @router.patch("/sites/{site_id}")
    async def site_patch(site_id: str, payload: SiteInput, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "sites", site_id)
            item = {**old, **payload.model_dump()}
            if old["qr_mode"] != item["qr_mode"]:
                item.update(qr_hash=digest(token()), qr_secret=token())
            await tx.put("sites", site_id, item)
            await service.audit(tx, actor, "sites", site_id, old, item)
            return public(item)

    @router.post("/sites/{site_id}/qr/reissue")
    async def site_reissue(site_id: str, t=Depends(tenant), actor=Depends(admin)):
        code = token()
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "sites", site_id)
            item = {**old, "qr_hash": digest(code), "qr_secret": token()}
            await tx.put("sites", site_id, item)
            await service.audit(tx, actor, "sites", site_id, old, item)
        return {
            "qr_token": code,
            "check_url": service.config.mobile_base_url
            + "?"
            + urlencode({"site": site_id, "t": code}),
        }

    @router.post("/employees/{employee_id}/mobile-invite")
    async def invite(employee_id: str, t=Depends(tenant), actor=Depends(admin)):
        code = token()
        async with service.repository.transaction(t) as tx:
            await service.require(tx, "employees", employee_id)
            for old in await tx.list("mobile_invites"):
                if old["employee_id"] == employee_id and not old.get("used_at"):
                    await tx.delete("mobile_invites", old["id"])
            item = dict(
                id=uid(),
                employee_id=employee_id,
                code_hash=digest(code),
                used_at=None,
                expires_at=(service.now() + timedelta(hours=24)).isoformat(),
            )
            await tx.put("mobile_invites", item["id"], item)
            await service.audit(tx, actor, "mobile_invites", item["id"], None, item)
        return {
            "code": code,
            "expires_at": public(item["expires_at"]),
            "invite_url": service.config.mobile_base_url + "?" + urlencode({"invite": code}),
        }

    @router.delete("/employees/{employee_id}/mobile-device")
    async def revoke_mobile(employee_id: str, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "mobile_devices", employee_id)
            item = {**old, "revoked_at": service.now().isoformat()}
            await tx.put("mobile_devices", employee_id, item)
            await service.audit(tx, actor, "mobile_devices", employee_id, old, item)
        return {"revoked": True}

    @router.get("/mobile/config", response_model=MobileConfigOutput)
    async def mobile_config(t=Depends(tenant)):
        async with service.repository.transaction(t) as tx:
            settings = await service.settings(tx)
            return {
                k: settings[k]
                for k in (
                    "consent_text",
                    "consent_version",
                    "location_months",
                    "confirm_before_checkin",
                    "show_retry_outside",
                    "allow_my_records",
                )
            }

    @router.post("/mobile/register")
    async def register(payload: RegisterInput, t=Depends(tenant)):
        issued = token()
        async with service.repository.transaction(t) as tx:
            invites = [
                i
                for i in await tx.list("mobile_invites")
                if hmac.compare_digest(i["code_hash"], digest(payload.code))
            ]
            if (
                not invites
                or invites[0].get("used_at")
                or instant(invites[0]["expires_at"]) <= service.now()
            ):
                fail(401, "invite expired or used")
            invite = invites[0]
            employee = await service.require(tx, "employees", invite["employee_id"])
            if not employee["active"]:
                fail(403, "employee inactive")
            settings = await service.settings(tx)
            if payload.consent_version != settings["consent_version"]:
                fail(409, "consent version changed")
            old = await tx.get("mobile_devices", employee["id"])
            if old and not old.get("revoked_at"):
                fail(409, "employee already has an active device")
            item = dict(
                id=employee["id"],
                employee_id=employee["id"],
                token_hash=digest(issued),
                device_label=payload.device_label,
                created_at=service.now().isoformat(),
                expires_at=(service.now() + timedelta(days=90)).isoformat(),
                revoked_at=None,
                consent_at=service.now().isoformat(),
                consent_version=payload.consent_version,
                consent_text=settings["consent_text"],
            )
            await tx.put("mobile_devices", employee["id"], item)
            await tx.put(
                "mobile_invites", invite["id"], {**invite, "used_at": service.now().isoformat()}
            )
        return {"token": issued, "expires_at": public(item["expires_at"])}

    @router.post("/mobile/token/refresh")
    async def refresh(t=Depends(tenant), auth=Depends(bearer)):
        issued = token()
        async with service.repository.transaction(t) as tx:
            device, _ = await service.mobile_device(tx, auth)
            item = {
                **device,
                "token_hash": digest(issued),
                "expires_at": (service.now() + timedelta(days=90)).isoformat(),
            }
            await tx.put("mobile_devices", device["id"], item)
        return {"token": issued, "expires_at": public(item["expires_at"])}

    @router.get("/mobile/me", response_model=MobileMeOutput)
    async def me(t=Depends(tenant), auth=Depends(bearer)):
        async with service.repository.transaction(t) as tx:
            _, employee = await service.mobile_device(tx, auth)
            record = await tx.get("attendance", f"{employee['id']}:{local_day(service.now())}")
            return {"employee_name": employee["name"], "record": public(record)}

    @router.get("/mobile/site", response_model=SiteInfoOutput)
    async def site_info(site_token: str, t=Depends(tenant), auth=Depends(bearer)):
        async with service.repository.transaction(t) as tx:
            _, employee = await service.mobile_device(tx, auth)
            site = await service.resolve_site(tx, site_token)
            key = f"{employee['id']}:{local_day(service.now())}"
            saved = await tx.get("attendance", key)
            if saved:
                rule = Rules(**saved["rule_snapshot"])
            else:
                _, rule = await service.effective_rule(
                    tx, employee["id"], local_day(service.now()), site["id"]
                )
            override = await service.active_override(tx, employee["id"], service.now())
            preview = judge_scan(
                service.now(),
                DayRecord.from_dict(saved) if saved else None,
                rule,
                force_out=override is not None,
            )
            return {
                **{k: site[k] for k in ("id", "name", "lat", "lng", "radius_m")},
                "server_time": public(service.now().isoformat()),
                "preview": preview.kind,
            }

    @router.post("/mobile/checkins", response_model=CheckResultOutput)
    async def checkin(payload: MobileCheckIn, t=Depends(tenant), auth=Depends(bearer)):
        return public(
            await service.record_scan(
                source="mobile",
                tenant_id=t,
                mobile_token=auth,
                site_token=payload.site_token,
                lat=payload.lat,
                lng=payload.lng,
                accuracy=payload.accuracy,
            )
        )

    @router.get("/mobile/attendance", response_model=list[AttendanceOutput])
    async def my_records(month: str, t=Depends(tenant), auth=Depends(bearer)):
        async with service.repository.transaction(t) as tx:
            _, employee = await service.mobile_device(tx, auth)
            if not (await service.settings(tx))["allow_my_records"]:
                fail(403, "record viewing disabled")
            return public(await records(tx, month=month, employee=employee["id"]))

    @router.post("/devices", status_code=201)
    async def device_create(payload: DeviceInput, t=Depends(tenant), actor=Depends(admin)):
        code = token()
        async with service.repository.transaction(t) as tx:
            await service.require(tx, "sites", payload.site_id)
            item = dict(
                id=uid(),
                **payload.model_dump(),
                kind="site_display",
                code_hash=digest(code),
                expires_at=(service.now() + timedelta(hours=24)).isoformat(),
                token_hash="",
                revoked_at=None,
                created_at=service.now().isoformat(),
            )
            await tx.put("devices", item["id"], item)
            await service.audit(tx, actor, "devices", item["id"], None, item)
        return {**public(item), "code": code}

    @router.get("/devices")
    async def devices(t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            return public(await tx.list("devices"))

    @router.delete("/devices/{device_id}")
    async def device_revoke(device_id: str, t=Depends(tenant), actor=Depends(admin)):
        async with service.repository.transaction(t) as tx:
            old = await service.require(tx, "devices", device_id)
            item = {**old, "revoked_at": service.now().isoformat()}
            await tx.put("devices", device_id, item)
            await service.audit(tx, actor, "devices", device_id, old, item)
            return public(item)

    @router.post("/devices/register")
    async def device_register(payload: DeviceRegisterInput, t=Depends(tenant)):
        issued = token()
        async with service.repository.transaction(t) as tx:
            matches = [
                d for d in await tx.list("devices") if d.get("code_hash") == digest(payload.code)
            ]
            if (
                not matches
                or matches[0].get("revoked_at")
                or matches[0].get("token_hash")
                or instant(matches[0]["expires_at"]) <= service.now()
            ):
                fail(401, "invalid registration code")
            device = matches[0]
            await tx.put(
                "devices", device["id"], {**device, "token_hash": digest(issued), "code_hash": ""}
            )
        return {"token": issued}

    @router.get("/sites/{site_id}/qr/current")
    async def current_qr(site_id: str, t=Depends(tenant), auth=Depends(bearer)):
        async with service.repository.transaction(t) as tx:
            matches = [d for d in await tx.list("devices") if d["token_hash"] == digest(auth)]
            if not matches:
                fail(401, "invalid display token")
            device = matches[0]
            if device.get("revoked_at") or device["site_id"] != site_id:
                fail(403, "device cannot access site")
            site = await service.require(tx, "sites", site_id)
            if not site["active"] or site["qr_mode"] != "rotating":
                fail(403, "rotating site required")
            stamp = int(service.now().timestamp()) // 30
            signature = hmac.new(
                site["qr_secret"].encode(), f"{site_id}.{stamp}".encode(), "sha256"
            ).hexdigest()
            value = f"{site_id}.{stamp}.{signature}"
            return {
                "site_token": value,
                "expires_at": public(
                    service.now().fromtimestamp((stamp + 1) * 30, service.now().tzinfo).isoformat()
                ),
                "check_url": service.config.mobile_base_url
                + "?"
                + urlencode({"site": site_id, "t": value}),
            }

    return router
