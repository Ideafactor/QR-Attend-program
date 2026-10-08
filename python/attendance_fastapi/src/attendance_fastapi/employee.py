"""Optional self-service routes. The host alone resolves an authenticated employee ID."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime
from .routes import public
from .schemas import EmployeeQrOutput, EmployeeStatusOutput, QrErrorOutput


def create_employee_router(attendance, employee_dependency, *, tenant_id="default", prefix="/me"):
    router = APIRouter(prefix=prefix, tags=["attendance-self"])

    def employee_id(value=Depends(employee_dependency)):
        if not isinstance(value, str) or not value or len(value) > 128:
            raise HTTPException(401, "authenticated employee required")
        return value

    @router.get("/qr", response_model=EmployeeQrOutput, responses={503: {"model": QrErrorOutput}})
    async def qr(response: Response, employee=Depends(employee_id)):
        response.headers["Cache-Control"] = "no-store"
        return public(await attendance.issue_employee_qr(employee, tenant_id=tenant_id))

    @router.get("/status", response_model=EmployeeStatusOutput)
    async def status(
        response: Response, since: AwareDatetime | None = None, employee=Depends(employee_id)
    ):
        response.headers["Cache-Control"] = "no-store"
        return public(
            await attendance.get_employee_status(employee, tenant_id=tenant_id, since=since)
        )

    return router
