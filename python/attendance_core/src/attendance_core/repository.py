from contextlib import AbstractAsyncContextManager
from typing import Protocol


class Transaction(Protocol):
    async def get(self, table: str, key: str) -> dict | None: ...
    async def list(self, table: str) -> list[dict]: ...
    async def put(self, table: str, key: str, data: dict) -> None: ...
    async def delete(self, table: str, key: str) -> None: ...


class AttendanceRepository(Protocol):
    """Transactions must serialize writes per tenant and commit/rollback all tables atomically.

    Custom adapters must include qr_uses and scan_resolutions (v2), reject duplicate
    consumption keys, and preserve original scans except explicit retention redaction.
    """

    def transaction(self, tenant_id: str) -> AbstractAsyncContextManager[Transaction]: ...
