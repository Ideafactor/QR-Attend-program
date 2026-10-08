"""Tenant-bound, server-signed employee QR. No host identity or persistence dependency."""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from . import UTC, aware

QR_INTERVAL_SECONDS = 60
MAX_QR_LENGTH = 1024


class DynamicQrError(ValueError):
    def __init__(self, code="ATTENDANCE_QR_INVALID"):
        self.code = code
        super().__init__(code)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _signature(payload: str, secret: str) -> str:
    if len(secret.encode()) < 32:
        raise ValueError("QR signing secret must contain at least 32 bytes")
    return _encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


@dataclass(frozen=True)
class DynamicQr:
    token: str
    employee_id: str
    tenant_id: str
    issued_at: datetime
    expires_at: datetime

    @property
    def token_hash(self):
        return hashlib.sha256(self.token.encode()).hexdigest()


def issue_dynamic_qr(employee_id: str, secret: str, now: datetime, *, tenant_id="default"):
    if not all(isinstance(v, str) and 0 < len(v) <= 128 for v in (employee_id, tenant_id)):
        raise ValueError("employee and tenant IDs must be 1..128 characters")
    slot = int(aware(now).timestamp()) // QR_INTERVAL_SECONDS
    payload = "aqr2." + _encode(
        json.dumps(
            [hashlib.sha256(tenant_id.encode()).hexdigest(), employee_id, slot],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    )
    token = payload + "." + _signature(payload, secret)
    if len(token) > MAX_QR_LENGTH:
        raise ValueError("encoded QR exceeds maximum length")
    issued = datetime.fromtimestamp(slot * QR_INTERVAL_SECONDS, UTC)
    return DynamicQr(token, employee_id, tenant_id, issued, issued + timedelta(seconds=60))


def verify_dynamic_qr(token: str, secret: str, now: datetime, *, tenant_id="default"):
    if not isinstance(token, str) or len(token) > MAX_QR_LENGTH or not token.isascii():
        raise DynamicQrError()
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "aqr2":
        raise DynamicQrError()
    payload = ".".join(parts[:2])
    if not hmac.compare_digest(parts[2], _signature(payload, secret)):
        raise DynamicQrError()
    try:
        tenant, employee, slot = json.loads(
            base64.b64decode(parts[1] + "=" * (-len(parts[1]) % 4), altchars=b"-_", validate=True)
        )
        if (
            tenant != hashlib.sha256(tenant_id.encode()).hexdigest()
            or not isinstance(employee, str)
            or not 0 < len(employee) <= 128
        ):
            raise ValueError()
        if type(slot) is not int or slot < 0:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError) as error:
        raise DynamicQrError() from error
    current = int(aware(now).timestamp()) // QR_INTERVAL_SECONDS
    if slot != current:
        raise DynamicQrError("ATTENDANCE_QR_EXPIRED")
    # Canonical encoding prevents multiple signed representations of one slot.
    qr = issue_dynamic_qr(employee, secret, now, tenant_id=tenant_id)
    if not hmac.compare_digest(qr.token, token):
        raise DynamicQrError()
    return qr
