"""Opt-in USB keyboard scanner router; never grants admin access."""

import hmac
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from attendance_fastapi.routes import public
from attendance_fastapi.schemas import CheckResultOutput, ScannerSessionOutput, QrErrorOutput


class ScannerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=1024, pattern=r"^[A-Za-z0-9._-]+$")


def create_scanner_router(
    attendance, *, token: Callable[[], str | None], tenant_id="default", prefix="/scanner"
):
    router = APIRouter(prefix=prefix, tags=["attendance-scanner"])

    def authenticate(response: Response, authorization: str | None = Header(default=None)):
        expected = token()
        if not expected:
            raise HTTPException(503, "Scanner access is not configured")
        if not authorization or not hmac.compare_digest(
            authorization.encode(), ("Bearer " + expected).encode()
        ):
            raise HTTPException(401, "Invalid scanner credentials")
        response.headers["Cache-Control"] = "no-store"

    @router.get(
        "/session", response_model=ScannerSessionOutput, dependencies=[Depends(authenticate)]
    )
    async def session():
        if attendance.config.employee_qr_mode == "rotating":
            attendance.qr_secret()
        return ScannerSessionOutput(qr_mode=attendance.config.employee_qr_mode)

    @router.post(
        "/scans",
        response_model=CheckResultOutput,
        dependencies=[Depends(authenticate)],
        responses={status: {"model": QrErrorOutput} for status in (409, 410, 422, 503)},
    )
    async def scan(body: ScannerInput):
        return public(await attendance.record_scan(body.code, source="kiosk", tenant_id=tenant_id))

    return router
