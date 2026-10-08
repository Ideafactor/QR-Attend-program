"""Frozen schema used by revision att_0001; never change after first release."""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    JSON,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

# Typed projections permit indexing/reporting without coupling the repository
# protocol to SQLAlchemy. The complete, versionable payload remains in data.
FIELDS = {
    "employees": {
        "name": String(200),
        "host_user_id": String(200),
        "qr_hash": String(64),
        "active": Boolean,
        "exited_at": Date,
        "legal_hold": Boolean,
        "created_at": DateTime(timezone=True),
    },
    "work_rules": {
        "group_id": String(128),
        "name": String(200),
        "effective_from": Date,
        "is_default": Boolean,
        "created_at": DateTime(timezone=True),
    },
    "assignments": {
        "kind": String(32),
        "target_id": String(128),
        "rule_id": String(128),
        "effective_from": Date,
        "effective_to": Date,
    },
    "teams": {"name": String(200)},
    "memberships": {
        "employee_id": String(128),
        "team_id": String(128),
        "effective_from": Date,
        "effective_to": Date,
    },
    "scans": {
        "employee_id": String(128),
        "scanned_at": DateTime(timezone=True),
        "source": String(16),
        "site_id": String(128),
        "lat": Float,
        "lng": Float,
        "accuracy_m": Float,
        "distance_m": Float,
        "result": String(32),
        "pending_status": String(32),
        "pending_reason": String(32),
    },
    "attendance": {
        "employee_id": String(128),
        "work_date": Date,
        "in_at": DateTime(timezone=True),
        "credited_in_at": DateTime(timezone=True),
        "expected_out_at": DateTime(timezone=True),
        "out_at": DateTime(timezone=True),
        "in_kind": String(32),
        "out_kind": String(32),
        "rule_id": String(128),
        "protected": Boolean,
        "label": String(200),
    },
    "sites": {
        "name": String(200),
        "lat": Float,
        "lng": Float,
        "radius_m": Float,
        "qr_mode": String(16),
        "qr_hash": String(64),
        "active": Boolean,
    },
    "devices": {
        "site_id": String(128),
        "token_hash": String(64),
        "revoked_at": DateTime(timezone=True),
    },
    "mobile_devices": {
        "employee_id": String(128),
        "token_hash": String(64),
        "expires_at": DateTime(timezone=True),
        "revoked_at": DateTime(timezone=True),
    },
    "mobile_invites": {
        "employee_id": String(128),
        "code_hash": String(64),
        "expires_at": DateTime(timezone=True),
        "used_at": DateTime(timezone=True),
    },
    "audit_logs": {
        "actor_id": String(200),
        "target_table": String(64),
        "target_id": String(128),
        "created_at": DateTime(timezone=True),
    },
    "settings": {},
    "scan_overrides": {
        "employee_id": String(128),
        "expires_at": DateTime(timezone=True),
        "consumed_at": DateTime(timezone=True),
        "cancelled_at": DateTime(timezone=True),
    },
}


def build_schema():
    metadata = MetaData()
    tables = {}
    for name, fields in FIELDS.items():
        columns = [
            Column("tenant_id", String(128), primary_key=True),
            Column("id", String(128), primary_key=True),
            Column("data", JSON, nullable=False),
        ]
        columns.extend(Column(key, datatype) for key, datatype in fields.items())
        constraints = []
        if name == "attendance":
            constraints.append(
                UniqueConstraint(
                    "tenant_id", "employee_id", "work_date", name="uq_att_employee_day"
                )
            )
        if name == "employees":
            constraints.append(UniqueConstraint("tenant_id", "qr_hash", name="uq_att_employee_qr"))
        tables[name] = Table("att_" + name, metadata, *columns, *constraints)
        for key in (
            "employee_id",
            "target_id",
            "effective_from",
            "scanned_at",
            "work_date",
            "pending_status",
        ):
            if key in fields:
                Index(f"ix_att_{name}_{key}", tables[name].c.tenant_id, tables[name].c[key])
    return metadata, tables
