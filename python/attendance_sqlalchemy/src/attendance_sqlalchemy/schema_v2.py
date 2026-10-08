"""Additive schema v2. The frozen schema_v1 remains unchanged."""

from sqlalchemy import Column, DateTime, JSON, String, Table, Index
from .schema_v1 import build_schema as build_v1


def add_v2_tables(metadata):
    tables = {}
    for name, fields in {
        "qr_uses": {
            "employee_id": String(128),
            "issued_at": DateTime(timezone=True),
            "expires_at": DateTime(timezone=True),
            "consumed_at": DateTime(timezone=True),
            "scan_id": String(128),
        },
        "scan_resolutions": {
            "employee_id": String(128),
            "pending_status": String(32),
            "processed_at": DateTime(timezone=True),
            "processed_by": String(200),
        },
    }.items():
        tables[name] = Table(
            "att_" + name,
            metadata,
            Column("tenant_id", String(128), primary_key=True),
            Column("id", String(128), primary_key=True),
            Column("data", JSON, nullable=False),
            *(Column(key, datatype) for key, datatype in fields.items()),
        )
        Index(f"ix_att_{name}_employee", tables[name].c.tenant_id, tables[name].c.employee_id)
    return tables


def build_schema():
    metadata, tables = build_v1()
    tables.update(add_v2_tables(metadata))
    return metadata, tables
