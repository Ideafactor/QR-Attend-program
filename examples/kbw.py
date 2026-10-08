"""Compatibility wrapper for the example host."""

from attendance_fastapi import create_scanner_router


def scanner_router(attendance, *, token, tenant_id="default"):
    return create_scanner_router(
        attendance, token=token, tenant_id=tenant_id, prefix="/api/scanner"
    )
