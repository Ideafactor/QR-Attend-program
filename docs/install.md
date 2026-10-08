# 다른 프로젝트에 설치하기 — 0.2.0

## 지원 범위

Python 3.11+ / FastAPI / SQLAlchemy 2 서버에 설치합니다. UI는 React 18~19 선택 패키지입니다. PostgreSQL을 운영 DB로 권장하며 SQLite는 로컬 테스트에 사용합니다. 다른 언어의 서버는 이 Python 서비스를 별도로 운영하고 HTTP로 연결해야 합니다. 어떤 프레임워크에도 자동 설치되는 플러그인은 아닙니다.

배포 파일: `attendance-0.2.0-bundle.tar.gz`. 압축을 풀면 Python wheel 3개, sdist 3개, npm tgz 3개, 독립 실행 예제 `app.py`, 설치 문서와 SHA256SUMS가 있습니다. 패키지는 포함되지만 외부 의존성까지 포함된 완전 오프라인 배포는 아닙니다. 레지스트리 게시 없이 파일로 설치할 수 있습니다.

## 1. 압축 해제와 로컬 동작 확인

```sh
tar -xzf attendance-0.2.0-bundle.tar.gz
cd attendance-0.2.0
shasum -a 256 -c SHA256SUMS
python3 -m venv .venv
.venv/bin/python -m pip install --find-links . 'attendance-core==0.2.0' 'attendance-fastapi==0.2.0' 'attendance-sqlalchemy[sqlite]==0.2.0' uvicorn
export ATTENDANCE_ADMIN_TOKEN='별도로-정한-관리자-키'
export ATTENDANCE_SCANNER_TOKEN='관리자와-다른-스캐너-키'
# 다음 값은 예시입니다. 운영에서는 충분히 긴 무작위 비밀값을 별도로 생성하세요.
export ATTENDANCE_QR_SIGNING_SECRET='replace-with-a-random-secret-at-least-32-bytes'
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8017
```

`http://127.0.0.1:8017/docs`에서 API를 확인합니다. 이 예제는 로컬 SQLite 테이블을 생성하며 기본 패키지 규칙을 사용합니다. 각 사이트의 근무 규칙은 관리자 API로 등록합니다. 이 app.py의 단순 관리자 키 인증과 기동 시 테이블 생성은 개발 예시입니다.

## 2. 기존 Python 프로젝트에 설치

wheel 3개를 프로젝트의 `vendor/attendance/`에 넣고 의존성 관리 도구에 등록합니다. uv 예:

```sh
uv add ./vendor/attendance/attendance_core-0.2.0-py3-none-any.whl ./vendor/attendance/attendance_fastapi-0.2.0-py3-none-any.whl ./vendor/attendance/attendance_sqlalchemy-0.2.0-py3-none-any.whl
```

PostgreSQL이면 asyncpg, SQLite면 aiosqlite가 필요합니다. lockfile과 vendor를 함께 관리하고 Docker 의존성 설치 단계 전에 vendor를 COPY합니다. 개발 저장소의 절대 경로를 참조하지 않습니다.

```python
from attendance_fastapi import AttendanceConfig, create_attendance, create_scanner_router
from attendance_sqlalchemy import SqlAlchemyRepository

# host_session_factory: 호스트가 관리하는 async_sessionmaker
attendance = create_attendance(
    SqlAlchemyRepository(host_session_factory),
    config=AttendanceConfig(
        timezone="Asia/Seoul", mobile_base_url="https://YOUR_HOST/attendance/mobile",
        qr_signing_secret=settings.qr_signing_secret,
    ),
)
# require_admin: 호스트 세션/역할을 검증하고 감사용 관리자 ID를 반환하는 의존성
app.include_router(attendance.router(require_admin), prefix="/api/attendance")
# 명시적으로 등록할 때만 스캐너 API가 열립니다.
app.include_router(create_scanner_router(
    attendance,
    token=lambda: settings.scanner_token,
    prefix="/api/scanner",
    tenant_id="default",
))
```

`token` 콜백은 문자열 또는 None을 반환합니다. 비밀 타입을 쓰는 설정 시스템에서는 문자열로 꺼내 반환합니다. None/빈 값이면 스캐너 접근은 503으로 비활성화됩니다. 스캐너 키는 전용으로 설정하고 환경이나 비밀 저장소에서 관리합니다. 관리자·스캐너·모바일 권한을 섞지 않습니다.

사업장을 변경하면 규칙 초기화·관리자 API의 tenant_resolver·스캐너 tenant_id도 일치시킵니다. 테넌트는 호스트의 검증된 컨텍스트에서 정하며 클라이언트 헤더를 그대로 신뢰하지 않습니다.

## 3. 기존 DB 마이그레이션 연결

운영에서는 기동 시 create_schema를 호출하지 않습니다. 기존 Alembic 체인에 새 revision을 생성하고 신규 설치에서는 고정된 `attendance_sqlalchemy.schema_v2.build_schema()`를 호출해 테이블을 만듭니다.

```python
from alembic import op
from attendance_sqlalchemy.schema_v2 import build_schema

def upgrade():
    metadata, _ = build_schema()
    metadata.create_all(op.get_bind(), checkfirst=False)
```

revision/down_revision은 기존 프로젝트 체인을 유지합니다. 패키지의 독립 `att_0001` migration과 이 방식을 동시에 적용하지 않습니다. env.py의 target_metadata에는 기존 메타데이터와 `attendance_sqlalchemy.metadata`를 함께 등록합니다. 테이블이 이미 있으면 먼저 적용 이력을 확인합니다. 테스트 DB에서 upgrade와 drift 검사를 완료한 뒤 배포합니다. 운영 복구 시 출퇴근 테이블을 삭제하지 않습니다.

## 4. React 설치와 스캐너 화면

선택한 tgz와 클라이언트를 **같은 명령**으로 설치합니다. 모바일 패키지도 사용할 경우 함께 지정합니다.

```sh
npm install ./vendor/attendance/attendance-attendance-client-0.2.0.tgz ./vendor/attendance/attendance-attendance-react-scanner-0.2.0.tgz
```

Bun 사용 프로젝트는 동일한 파일 인수로 `bun add`를 사용합니다. React는 호스트 프로젝트가 제공합니다.

```tsx
import {AttendanceScanner} from '@attendance/attendance-react-scanner';
import '@attendance/attendance-react-scanner/style.css';

export function ScannerPage() {
  return <AttendanceScanner
    baseUrl="/api/scanner"
    title="본사 출퇴근"
    adminHref="/admin/attendance"
    timeZone="Asia/Seoul"
  />;
}
```

컴포넌트는 브라우저에서 작동합니다. Next.js 등에서는 클라이언트 컴포넌트로 감쌉니다. CSS import는 프레임워크가 허용하는 위치에 둡니다. 관리자 링크는 생략할 수 있습니다. 근무 규칙의 시간대는 서버 설정이고 timeZone prop은 결과 시각 표시용입니다.

서버 prefix와 baseUrl을 일치시키고 호스트 라우터에서 원하는 페이지에 연결합니다. 스캐너 요청은 `credentials: omit`으로 쿠키 없이 전용 Bearer 키를 사용합니다. 쿠키 인증 관리자 요청의 CSRF 보호는 그대로 유지합니다. 별도 origin이면 호스트에서 해당 origin과 Authorization 헤더를 허용하는 CORS를 구성합니다. 운영 통신은 HTTPS로 제공합니다.

기본 장치는 USB-COM이며 Web Serial 포트를 직접 선택합니다. 서버가 제공하는 통신 속도(기본 9600)와 실제 장치 설정을 맞춥니다. CR/LF로 프레임을 나누고 종료 문자 없는 장치는 마지막 수신 후 150ms에 처리합니다. 수신 byte 수와 마지막 수신 시각을 표시합니다. Web Serial을 지원하는 보안 컨텍스트(HTTPS 또는 localhost)에서 사용하며, API 미지원 브라우저는 안내와 KBW 비상 입력을 제공합니다. KBW는 영문 입력·Enter 종료·입력창 포커스가 필요합니다.

대기열은 처리 중인 1건 외 최대 10건입니다. 초과 QR은 버리고 재스캔 안내를 표시합니다. 포트 해제 시 미완성 프레임을 폐기하고 통신 결과 불확실 시 전체 대기열을 비웁니다. 실제 장치 연결은 자동 테스트와 별도로 확인합니다.

## 5. 호스트에서 구현할 부분

- 기존 직원 ID를 host_user_id와 연결하고 중복 생성 방지, 팀·이름·비활성 상태 동기화.
- 기존 관리자 인증, 역할 검사와 CSRF; 관리자 화면과 메뉴.
- 사업장별 근무 규칙과 적용일 등록. 샘플의 09:00~11:00 규칙을 다른 회사에 자동 적용하지 않음.
- 직원 QR 발급·재발급, 승인 대기와 긴급 일회성 퇴근 관리.
- 모바일 선택 시 초대·동의·HTTPS·GPS 및 회사 정책.
- DB 백업, 로그 비밀값 제거, 알림 채널과 보관·파기 정책.

스캐너만 설치해도 직원과 규칙이 자동 생성되지는 않습니다. 관리자 API는 클라이언트 패키지 또는 호스트 HTTP 클라이언트로 연결합니다. 결과/오류 응답은 호스트의 공통 응답 규약과 맞춥니다.

## 6. 검증과 업데이트

인증 오류, 직원 비활성, QR 재발급, 시간 경계, 중복 스캔, 날짜 예외, 긴급 퇴근, 통신 실패를 테스트합니다. 네트워크 오류 후 마지막 스캔은 저장됐을 수 있으므로 관리자 기록을 확인하며 자동 재전송하지 않습니다. 실제 USB 장치 검증은 별도로 수행합니다.

모든 attendance 패키지는 같은 버전으로 맞춥니다. 업데이트는 새 배포 파일을 복사하고 lockfile 갱신 → migration 확인 → 테스트 → Docker 빌드 → 배포 순서입니다. npm/PyPI 공개 게시와 운영 배포는 이 저장소에서 자동 수행하지 않습니다.

패키지 개발자가 배포 묶음을 다시 만들 때:

```sh
.venv/bin/python -m scripts.build_release
```

MaruLog 상세 연결은 함께 제공한 MARULOG.md를 참고합니다. 0.2.0부터 스캐너 소스 복사 대신 공개 Python 함수와 React 컴포넌트를 사용할 수 있습니다.


## 7. 0.1.x → 0.2.0 업그레이드 (필수)

### 판정 정책 변경

예정 퇴근 이전 재스캔은 `already_in`이며 `out_at`·원장의 수정 시각·출처를 변경하지 않습니다. 활성 직원별 일회성 override에 한해서 `early_out`이 가능합니다. 만료·취소·이미 소비한 지정은 적용되지 않습니다. 중복 간격 내 스캔은 `duplicate`로 기록하되 override를 소비하지 않습니다. 기존 원장은 업그레이드만으로 재판정하지 않습니다.

### 회전 QR과 재사용 방지

- `AttendanceConfig.qr_signing_secret`에 32바이트 이상의 비밀키를 설정합니다. 스캐너 인증 키와 별개이며 모든 API 인스턴스에 동일하게 배포합니다.
- `employee_qr_mode` 기본값은 `rotating`입니다. 장기 QR은 기본적으로 거부합니다. 기존 장기 QR이 필요한 이행 환경에서만 `employee_qr_mode="static"`을 명시합니다. static 모드에는 회전/소비 보호가 없습니다.
- QR은 서버 시각을 기준으로 한 60초 구간 동안 동일하며 다음 구간에서 만료됩니다. 발급 순간부터 무조건 60초 동안 유효한 것은 아닙니다.
- 형식은 `aqr2.<서명 대상 데이터>.<HMAC>`이며 사업장과 패키지 직원 ID에 결합합니다. MaruLog의 기존 `aqr1`/외부근무 QR과 호환되지 않습니다. 발급·검증을 함께 전환해야 합니다.
- 서비스의 `issue_employee_qr(employee_id, tenant_id=...)`로 발급합니다. 직원 생성 응답의 `qr_token`과 재발급 API는 legacy 정적 모드용이며 기본 스캐너에는 사용하지 않습니다.
- QR 원문은 DB에 저장하지 않습니다. `att_qr_uses.id`가 SHA-256 해시이며 직원·발급·만료·소비 시각·스캔 ID만 저장합니다.
- QR 소비, 스캔 이력, 원장, override 변경은 같은 트랜잭션입니다. 실패하면 모두 취소되고, 같은 QR의 동시 처리도 한 건만 성공합니다.
- 오류: 위조/다른 사업장/정적 QR `422 ATTENDANCE_QR_INVALID`, 만료 `410 ATTENDANCE_QR_EXPIRED`, 사용된 QR `409 ATTENDANCE_QR_ALREADY_USED`. 유효한 새 QR이 중복 시간 간격에 해당하면 200 `duplicate`이며 그 QR은 소비됩니다.

### 기존 DB 추가 마이그레이션

패키지 migration 체인을 사용하는 호스트는 `att_0001 → att_0002`를 적용합니다. 새 테이블은 `att_qr_uses`, `att_scan_resolutions` 두 개입니다. 기존 테이블과 데이터는 그대로 유지됩니다.

MaruLog처럼 기존 체인에 schema_v1을 직접 편입했다면 **새 host revision**에서 다음 부분만 실행합니다. 기존 revision을 schema_v2로 고치거나 기존 테이블을 다시 만들지 않습니다.

```python
from alembic import op
from sqlalchemy import MetaData
from attendance_sqlalchemy.schema_v2 import add_v2_tables

def upgrade():
    metadata = MetaData()
    add_v2_tables(metadata)
    metadata.create_all(op.get_bind(), checkfirst=False)
```

신규 설치는 schema_v2 전체를 생성하고, 기존 설치는 위 추가분만 생성합니다. `env.py`는 호스트 metadata와 최신 `attendance_sqlalchemy.metadata`를 함께 사용합니다. 이전 서버로 복구하더라도 새 원장을 삭제하지 않습니다.

### 스캔 이력 및 관리자 조회

`scans`의 원본 판정은 다시 쓰지 않습니다. 승인/무시는 `scan_resolutions`에 별도 저장하며 `projected_scans(tx)`가 현재 처리 상태를 합성합니다. 기존 0.1.x 승인 상태도 읽을 수 있습니다. 관리자 `/attendance`는 `scans` 요약과 `work_mode`를 제공합니다.

`OFFICE`/`EXTERNAL`/`MIXED`는 실제 원장에 반영된 in/out 출처로 계산합니다. 대기·중복·거부된 시도만으로 근무 유형을 바꾸지 않습니다. 관리자 수동 입력/수정은 `MANUAL`이 우선입니다. QR 소비 원장과 승인 상태는 append-only이며, 명시적인 기존 보관 정책에 따른 GPS 가림·직원 파기는 별도 예외입니다. 자동 파기 스케줄은 호스트가 결정합니다.

### 본인 QR와 상태 조회

호스트 로그인 사용자를 패키지 직원 ID로 매핑하는 의존성을 전달합니다. 클라이언트가 넘긴 직원 ID를 본인 인증으로 사용하지 않습니다.

```python
from attendance_fastapi import create_employee_router

# require_my_employee: 호스트 로그인 검증 후 패키지 employee ID 문자열 반환
app.include_router(create_employee_router(
    attendance, require_my_employee, tenant_id="default", prefix="/me"
), prefix="/api/attendance")
```

서비스만 사용할 경우 `get_employee_status(employee_id, tenant_id=..., since=...)`를 호출할 수 있습니다. `since`는 timezone-aware datetime입니다. `/me/qr`와 `/me/status`는 no-store 응답입니다.

```typescript
import {createAttendanceClient, hasQrScanResult} from '@attendance/attendance-client';
const client = createAttendanceClient({baseUrl:'/api/attendance', fetcher:hostAuthenticatedFetch});
const qr = await client.employee.getQr();
// qr.code로 QR을 표시하고 expires_at/server_time 기준으로 갱신합니다.
// 화면이 보이는 동안 겹치지 않게 주기적으로 조회합니다.
const status = await client.employee.getStatus(qr.generated_at);
if (hasQrScanResult(status)) {
  // 호스트 화면에서 QR을 숨기고 status.latest_scan과 attendance 결과를 표시합니다.
}
```

`issued_at`은 분 단위 구간 시작 시각이고 `generated_at`은 실제 요청 처리 시각입니다. 이전 스캔이 방금 발급한 QR의 결과로 보이지 않도록 상태 조회에는 **generated_at**을 사용합니다. 폴링 종료·QR 표시·화면 경로·세션은 호스트가 구현합니다.

### MaruLog 기존 어댑터 교체

공통 QR 발급/검증·비조기퇴근 보완·소비 원장·시리얼 화면을 패키지 호출로 바꿉니다. 기존 MaruLog QR 소비 트랜잭션과 플러그인 소비를 중복 실행하지 않습니다. 기존 MaruLog 소비 이력은 보존하고 새로운 형식부터 패키지 원장에 기록합니다. 계정 동기화·세션/CSRF/ADMIN·연차·외부근무 신청/승인·신청 번호·콘솔 배치·Tailscale/8008 설정은 이 패키지로 옮기지 않습니다.
