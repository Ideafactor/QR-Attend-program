from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator
from attendance_core import Rules


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuleInput(Input):
    name: str = Field(min_length=1, max_length=200)
    effective_from: date
    is_default: bool = False
    check_in_start: str = "08:00"
    work_start: str | None = None
    check_in_end: str = "11:00"
    check_out_start: str = "18:00"
    check_in_slots: list[str] = Field(default_factory=list)
    slot_grace_minutes: int = Field(default=10, ge=0, le=240)
    checkout_mode: Literal["fixed", "elapsed"] = "fixed"
    checkout_offset_minutes: int = Field(default=540, gt=0, lt=1440)
    missing_in_out_start: str = "18:00"
    after_slots: Literal["pending", "late"] = "pending"
    dedup_seconds: int = Field(default=60, ge=0, le=3600)

    @model_validator(mode="after")
    def validate_rule(self):
        Rules(**self.rule_values())
        return self

    def rule_values(self):
        return self.model_dump(exclude={"name", "effective_from", "is_default"})


class EmployeeInput(Input):
    name: str = Field(min_length=1, max_length=200)
    host_user_id: str | None = None


class EmployeePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None
    exited_at: date | None = None
    legal_hold: bool | None = None


class AssignmentInput(Input):
    rule_id: str | None
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("end precedes start")
        return self


class ExceptionInput(Input):
    rule_id: str
    date: date
    reason: str = Field(min_length=1, max_length=1000)


class OverrideInput(Input):
    mode: Literal["out"] = "out"
    label: Literal["오전반차", "오후반차", "조퇴", "외근", "휴가", "결근", "기타"]
    reason: str = Field(min_length=1, max_length=1000)
    expires_at: AwareDatetime


class ApproveInput(Input):
    as_: Literal["in", "out", "prev_out"] = Field(alias="as")


class ManualInput(Input):
    employee_id: str
    work_date: date
    in_at: AwareDatetime | None = None
    out_at: AwareDatetime | None = None
    label: str | None = None
    memo: str = Field(default="", max_length=2000)


class AttendancePatch(Input):
    in_at: AwareDatetime | None = None
    out_at: AwareDatetime | None = None
    label: str | None = None
    memo: str | None = Field(default=None, max_length=2000)


class RejudgeInput(Input):
    from_: date = Field(alias="from")
    to: date


class SiteInput(Input):
    name: str = Field(min_length=1, max_length=200)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    radius_m: float = Field(default=200, gt=0, le=100000, allow_inf_nan=False)
    qr_mode: Literal["static", "rotating"] = "static"
    active: bool = True


class RegisterInput(Input):
    code: str
    consent: Literal[True]
    device_label: str = Field(default="휴대폰", max_length=200)
    consent_version: str


class MobileCheckIn(Input):
    site_token: str
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy: float = Field(ge=0, le=100000, allow_inf_nan=False)


class DeviceInput(Input):
    name: str = Field(min_length=1, max_length=200)
    site_id: str


class DeviceRegisterInput(Input):
    code: str


class SettingsInput(Input):
    records_years_after_exit: int = Field(default=3, ge=3, le=100)
    location_months: int = Field(default=6, ge=0, le=120)
    invite_days: int = Field(default=30, ge=0, le=365)
    max_accuracy_m: float = Field(default=100, gt=0, allow_inf_nan=False)
    consent_text: str = "근태 확인을 위해 체크 순간의 위치를 수집합니다."
    consent_version: str = "1"
    confirm_before_checkin: bool = True
    show_retry_outside: bool = True
    allow_my_records: bool = True


class Output(BaseModel):
    model_config = ConfigDict(extra="allow")


class ScanSummary(Output):
    id: str
    employee_id: str
    scanned_at: AwareDatetime
    source: Literal["kiosk", "mobile"]
    result: str
    pending_status: str | None = None
    pending_reason: str | None = None


class AttendanceOutput(Output):
    id: str
    employee_id: str
    work_date: date
    in_at: AwareDatetime | None
    credited_in_at: AwareDatetime | None
    expected_out_at: AwareDatetime | None
    out_at: AwareDatetime | None
    in_kind: str | None
    out_kind: str | None
    protected: bool
    label: str | None = None
    work_mode: Literal["OFFICE", "EXTERNAL", "MIXED", "MANUAL"] | None = None
    scans: list[ScanSummary] = Field(default_factory=list)


class CheckResultOutput(Output):
    scan_id: str
    employee_id: str
    result: Literal[
        "in",
        "already_in",
        "tardy_in",
        "late_in",
        "out",
        "early_out",
        "out_no_in",
        "pending",
        "duplicate",
        "protected",
    ]
    employee_name: str
    recorded_at: AwareDatetime
    pending_reason: str | None = None
    distance_m: float | None = None
    radius_m: float | None = None
    record: AttendanceOutput | None = None


class MobileConfigOutput(Output):
    consent_text: str
    consent_version: str
    location_months: int
    confirm_before_checkin: bool
    show_retry_outside: bool
    allow_my_records: bool


class SiteInfoOutput(Output):
    id: str
    name: str
    lat: float
    lng: float
    radius_m: float
    preview: str
    server_time: AwareDatetime


class MobileMeOutput(Output):
    employee_name: str
    record: AttendanceOutput | None


class EmployeeQrOutput(Output):
    code: str
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    generated_at: AwareDatetime
    server_time: AwareDatetime
    interval_seconds: Literal[60] = 60


class EmployeeStatusOutput(Output):
    employee_id: str
    work_date: date
    server_time: AwareDatetime
    attendance: AttendanceOutput | None
    latest_scan: ScanSummary | None
    result_since: bool


class ScannerSessionOutput(Output):
    ready: Literal[True] = True
    transport: Literal["USB-COM"] = "USB-COM"
    fallback_transport: Literal["USB-KBW"] = "USB-KBW"
    baud_rate: Literal[9600] = 9600
    supported_baud_rates: list[int] = Field(
        default_factory=lambda: [9600, 19200, 38400, 57600, 115200]
    )
    terminator: Literal["CRLF"] = "CRLF"
    qr_interval_seconds: Literal[60] = 60
    queue_limit: Literal[10] = 10
    max_code_length: Literal[1024] = 1024
    qr_mode: Literal["rotating", "static"] = "rotating"


class QrErrorOutput(BaseModel):
    detail: Literal[
        "ATTENDANCE_QR_INVALID",
        "ATTENDANCE_QR_EXPIRED",
        "ATTENDANCE_QR_ALREADY_USED",
        "ATTENDANCE_QR_NOT_CONFIGURED",
        "ATTENDANCE_EMPLOYEE_INACTIVE",
    ]
