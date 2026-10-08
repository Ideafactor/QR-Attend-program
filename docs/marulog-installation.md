# MaruLog 출퇴근 패키지 설치·연동 매뉴얼

갱신일: 2026-10-01  
패키지 버전: 0.2.0  
원본: `~/Dev/plugin_attend`  
대상: `~/Dev/MaruLog`

이 문서는 설치 담당 개발자를 위한 절차서입니다. 패키지 파일은 준비되어 있지만 **MaruLog 연동 코드는 아직 구현되지 않았습니다.** 아래 명령과 코드 예시는 해당 단계에서 개발·검증한 뒤 적용합니다. 문서 작성 과정에서 MaruLog 소스나 운영 DB를 변경하지 않았습니다.

> 0.2.0 필수: 신규 설치와 기존 0.1.x 업그레이드는 DB 절차가 다릅니다. [범용 설치 매뉴얼 7장](install.md#7-01x--020-업그레이드-필수)의 추가 테이블·서명키·QR 형식 전환을 먼저 적용하세요. 기존 MaruLog 회전 QR 어댑터와 중복 소비하지 않습니다.

> 패키지 연결: 스캐너 API는 `attendance_fastapi.create_scanner_router`, 화면은 `@attendance/attendance-react-scanner`로 설치할 수 있습니다. 아래 예제 소스 이식 절차 대신 [범용 설치 매뉴얼](install.md)의 공개 함수를 사용하세요. 서버 prefix와 화면 baseUrl을 `/api/v1/attendance-scanner`로 맞추면 됩니다. 기존 직원·인증·DB 통합 작업은 여전히 필요합니다.

## 1. 설치 범위

MaruLog는 Python 3.13/FastAPI, React 19/TypeScript, PostgreSQL을 사용합니다. API 의존성은 uv, 웹 의존성과 Docker 웹 빌드는 Bun으로 관리합니다.

이번 1차 연결 범위는 관리자 출퇴근 관리, 기존 직원 연결, 직원 QR 발급, USB-KBW 스캐너입니다. 모바일 GPS 출퇴근은 선택적으로 이어서 연결합니다.

| 구성 | 역할 | 설치 대상 |
|---|---|---|
| attendance-core | 시간 규칙과 출퇴근 판정 | API |
| attendance-fastapi | 출퇴근 서비스와 API | API |
| attendance-sqlalchemy | DB 저장소와 테이블 정의 | API |
| @attendance/attendance-client | TypeScript 클라이언트와 타입 | 웹 |
| @attendance/attendance-react-mobile | 모바일 등록·GPS 체크 화면 | 웹, 선택 |
| examples/kbw.py | 스캐너 전용 서버 어댑터 | MaruLog에 소스 이식 |
| examples/web/scanner.tsx, scanner.css | USB-KBW 입력 화면 | MaruLog에 소스 이식 |

스캐너 화면·어댑터는 wheel이나 npm 패키지에 자동 설치되지 않습니다. 예제 관리자 화면도 MaruLog 권한과 디자인에 맞춰 별도로 이식해야 합니다.

## 2. 작업 공간과 사전 확인

MaruLog의 `AGENTS.md`와 다음 문서를 먼저 확인합니다.

- `docs/PRD_Worklog.md`
- `docs/architecture.md`
- `docs/ui-spec.md`
- `docs/api-contract.md`

공유 서버는 기존 작업 디렉터리와 8000 포트를 유지합니다. 별도 worktree와 8008 포트, 별도 테스트 DB에서 진행합니다. 기존 작업 내용을 확인하고 검증할 기준 커밋에서 분기하세요.

```sh
cd ~/Dev/MaruLog
git status --short
git worktree add ../MaruLog-attendance -b feature/attendance
```

이하 `~/Dev/MaruLog-attendance`를 작업 경로로 사용합니다. 이미 같은 이름이 있다면 다른 이름을 사용합니다. 운영 환경 파일을 그대로 복사하지 말고 테스트용 DB 연결을 준비합니다.

## 3. 배포 파일 복사 및 의존성 등록

### 3.1 파일 복사

```sh
cd ~/Dev/MaruLog-attendance
mkdir -p apps/api/vendor/attendance apps/web/vendor/attendance
cp ~/Dev/plugin_attend/dist/attendance-0.2.0/attendance_core-0.2.0-py3-none-any.whl apps/api/vendor/attendance/
cp ~/Dev/plugin_attend/dist/attendance-0.2.0/attendance_fastapi-0.2.0-py3-none-any.whl apps/api/vendor/attendance/
cp ~/Dev/plugin_attend/dist/attendance-0.2.0/attendance_sqlalchemy-0.2.0-py3-none-any.whl apps/api/vendor/attendance/
cp ~/Dev/plugin_attend/dist/attendance-0.2.0/attendance-attendance-client-0.2.0.tgz apps/web/vendor/attendance/
cp ~/Dev/plugin_attend/dist/attendance-0.2.0/attendance-attendance-react-scanner-0.2.0.tgz apps/web/vendor/attendance/
```

모바일도 연결할 때만 추가합니다.

```sh
cp ~/Dev/plugin_attend/dist/attendance-0.2.0/attendance-attendance-react-mobile-0.2.0.tgz apps/web/vendor/attendance/
```

### 3.2 API 의존성

세 wheel을 같은 명령에서 등록합니다. 내부 패키지 의존성을 레지스트리에서 찾지 않도록 모두 로컬 파일로 지정합니다.

```sh
cd ~/Dev/MaruLog-attendance/apps/api
uv add ./vendor/attendance/attendance_core-0.2.0-py3-none-any.whl ./vendor/attendance/attendance_fastapi-0.2.0-py3-none-any.whl ./vendor/attendance/attendance_sqlalchemy-0.2.0-py3-none-any.whl
uv sync --locked
uv run python -c 'import attendance_core, attendance_fastapi, attendance_sqlalchemy'
```

`pyproject.toml`과 `uv.lock`에 로컬 경로가 기록되는지 확인합니다. 개인 PC의 절대 경로나 `../plugin_attend`에 의존하는 설정은 배포에 사용하지 않습니다.

### 3.3 웹 의존성

```sh
cd ~/Dev/MaruLog-attendance/apps/web
bun add ./vendor/attendance/attendance-attendance-client-0.2.0.tgz ./vendor/attendance/attendance-attendance-react-scanner-0.2.0.tgz
```

모바일 선택 설치:

```sh
bun add ./vendor/attendance/attendance-attendance-react-mobile-0.2.0.tgz
```

`package.json`, `bun.lock`, vendor 파일을 함께 버전 관리합니다. 이 프로젝트에 npm lockfile을 추가하지 않습니다.

### 3.4 Dockerfile 수정

기존 Dockerfile은 의존성을 먼저 설치하고 나중에 소스를 복사합니다. 따라서 **의존성 설치 전에 vendor 디렉터리를 복사**해야 합니다.

웹 빌드 단계에서 `bun install` 앞에 추가:

```dockerfile
COPY apps/web/vendor/ ./vendor/
```

API 빌드 단계에서 `uv sync` 앞에 추가:

```dockerfile
COPY apps/api/vendor/ ./vendor/
```

`.dockerignore`가 vendor나 패키지 파일을 제외하지 않는지도 확인합니다. Docker 빌드는 worktree 루트를 컨텍스트로 사용합니다.

## 4. DB 마이그레이션 통합

### 신규 설치: MaruLog 마이그레이션 체인에 편입

이미 0.1.x를 적용한 DB에는 아래 전체 생성 코드를 실행하지 않습니다. 범용 매뉴얼 7장의 `add_v2_tables()` 추가 revision을 사용합니다.

MaruLog의 배포 스크립트는 `alembic upgrade head`를 사용합니다. 출퇴근 패키지의 독립 revision `att_0001`을 그대로 추가하면 두 개의 head가 생길 수 있으므로, 이번 통합은 **MaruLog의 새 revision에서 고정된 schema_v2를 호출하는 방식**을 사용합니다.

```sh
cd ~/Dev/MaruLog-attendance/apps/api
uv run alembic heads
uv run alembic revision -m "add attendance tables"
```

생성된 revision의 `revision`, `down_revision`은 MaruLog 체인을 유지하고, 본문을 다음 형태로 작성합니다.

```python
from alembic import op
from attendance_sqlalchemy.schema_v2 import build_schema


def upgrade() -> None:
    metadata, _ = build_schema()
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    metadata, _ = build_schema()
    metadata.drop_all(op.get_bind(), checkfirst=False)
```

주의사항:

- 이 방식과 패키지의 별도 `att_0001` 적용을 병행하지 않습니다.
- 이미 `att_` 테이블이 존재하는 DB는 먼저 적용 이력을 조사합니다. 무조건 재실행하거나 stamp로 건너뛰지 않습니다.
- API 서버 기동 시 `create_schema()`를 호출하지 않습니다.
- 이후 패키지 스키마 변경도 MaruLog revision으로 명시적으로 반영합니다.
- downgrade는 출퇴근 데이터를 삭제하므로 운영 복구 방법으로 사용하지 않습니다.

### 메타데이터 반영

`apps/api/alembic/env.py`의 비교 대상에 출퇴근 메타데이터를 추가합니다.

```python
from attendance_sqlalchemy import metadata as attendance_metadata

target_metadata = [Base.metadata, attendance_metadata]
```

기존 `Base.metadata`를 유지합니다. 출퇴근 메타데이터가 빠지면 `alembic check`에서 추가 테이블을 삭제 대상으로 판단할 수 있습니다.

테스트 DB를 가리키는 설정에서 실행합니다.

```sh
uv run alembic upgrade head
uv run alembic current --check-heads
uv run alembic check
```

런타임은 MaruLog의 pooled URL, 마이그레이션은 direct URL을 사용합니다. 기존 데이터와 `att_` 테이블이 함께 존재하고 재실행 시 변경이 없는지 확인합니다.

## 5. API 서비스와 관리자 인증 연결

권장 추가 구조:

```text
apps/api/app/attendance/
  __init__.py
  integration.py       # 서비스 생성과 라우터 등록
  scanner.py           # KBW 어댑터 이식
  employee_sync.py     # 기존 직원 매핑·상태 동기화
  seed.py              # 초기 규칙 등록 명령
```

`apps/api/app/main.py`의 `create_app()`이 만드는 세션 팩토리 `factory`를 재사용합니다. 테스트가 주입한 팩토리도 그대로 전달해야 테스트 DB 대신 실제 DB에 연결하는 사고를 막을 수 있습니다.

연결 형태 예시:

```python
repository = SqlAlchemyRepository(factory)
attendance = create_attendance(repository, config=AttendanceConfig(qr_signing_secret=settings.qr_signing_secret))
application.include_router(
    attendance.router(require_attendance_admin),
    prefix="/api/v1/attendance",
)
```

관리자 의존성은 `app.auth.context.require_principal`과 `EmployeeRole.ADMIN`을 사용해 검증하고, 감사 이력용으로 `str(principal.employee_id)`를 반환하도록 구현합니다. MEMBER·LEADER에는 관리자 API를 허용하지 않습니다. 예제의 `ATTENDANCE_ADMIN_TOKEN` 인증은 MaruLog에 사용하지 않습니다.

기존 서버 세션, 강제 비밀번호 변경 제한, CSRF 검증을 유지합니다. 관리자 클라이언트의 변경 요청에는 `X-CSRF-Token`을 전달합니다. MaruLog 오류 응답 형식과 패키지 오류 메시지의 차이를 어댑터에서 처리하고 `docs/api-contract.md`에 경로·입출력·오류를 문서화합니다.

## 6. 직원 및 근무 규칙 연결

### 직원 매핑

| MaruLog | 출퇴근 패키지 |
|---|---|
| employee.id | host_user_id에 문자열로 저장 |
| employee.name | name |
| primary_team_id | 출퇴근 규칙에 사용할 팀 식별자로 매핑 |
| status / deleted_at | active 여부로 반영 |

`host_user_id`만 설정한다고 자동 동기화되지 않습니다. 별도 동기화 코드를 구현해야 합니다.

- 같은 직원이 중복 생성되지 않도록 재실행 가능한 초기 동기화와 중복 방지를 구현합니다.
- 기존 직원 추가·이름 변경·팀 변경·비활성화 경로에서 출퇴근 정보를 동기화합니다.
- 퇴사·비활성 직원은 다음 스캔부터 차단되어야 합니다. 동기화 실패 시 재처리와 스캔 차단 방안을 구현합니다.
- 직원 QR은 인증된 본인 화면에서 60초 구간마다 발급·갱신합니다. 기본 모드에서는 기존 장기 QR을 사용하지 않습니다.
- 일반 직원용 조회를 추가한다면 서버의 로그인 직원 ID로 대상을 제한합니다. 관리자 조회 API를 그대로 공개하지 않습니다.

### 초기 규칙

`plugin_attend/examples/work-rule.json`을 참고해 일회성 초기화 명령에서 `attendance.seed_rules()`로 등록합니다. 이미 DB에 규칙이 있으면 초기 파일로 덮어쓰지 않습니다.

| 항목 | 이번 테스트 장소 기준 |
|---|---|
| 출근 구간 | 09:00 / 09:30 / 10:00 / 10:30 / 11:00 |
| 인정 여유 | 10분: 09:10:59까지 09:00 인정 |
| 정상 퇴근 | 인정 출근 + 540분: 09:00→18:00, 11:00→20:00 |
| 영상팀 13시 | 보고된 직원·특정 날짜에만 예외 등록 |
| 집계 | 가장 빠른 유효 출근, 이후 유효 스캔 중 가장 늦은 퇴근 |
| 출근 없는 퇴근 | 출근 누락 표시 |
| 긴급 휴가·조퇴 | 관리자 직원별 일회성 퇴근 지정 후 QR 스캔 |
| 중복 방지 | 기본 60초 |

위 값은 MaruLog 전체에 이미 확정된 운영 규칙이 아니라 현재 합의한 테스트 장소 기준입니다. 도입 사업장을 서버에서 지정하고 운영 적용일을 정해 등록합니다.

## 7. USB-COM / USB-KBW 스캐너 연결

1. `attendance_fastapi.create_scanner_router`를 호출하는 호스트 연결 코드를 작성합니다.
2. 라우터 prefix를 `/api/v1/attendance-scanner`로 변경합니다.
3. 기존 `attendance` 인스턴스를 전달합니다. 스캐너만 별도 DB나 서비스를 만들지 않습니다.
4. `ATTENDANCE_SCANNER_TOKEN`을 MaruLog 설정에 비밀값으로 추가합니다. 관리자 로그인 정보와 별개이며 프론트 빌드 변수에 넣지 않습니다.
5. 사업장 `tenant_id`는 서버에서 고정합니다. 관리자·규칙 초기화·스캐너가 같은 값을 사용해야 합니다.
6. 화면의 요청 주소도 변경합니다.

| 요청 | 역할 |
|---|---|
| GET /api/v1/attendance-scanner/session | 스캐너 인증 확인 |
| POST /api/v1/attendance-scanner/scans | QR 기록 |

POST 본문은 `{"code":"직원 QR 원문"}`만 받습니다. 시각·직원 ID·사업장·출퇴근 모드는 클라이언트가 정하지 않습니다.

### 세션 쿠키와 충돌 방지

현재 예제 fetch는 같은 origin 쿠키를 함께 보낼 수 있습니다. MaruLog로 이식하는 스캐너 fetch는 두 요청 모두 `credentials: "omit"`을 사용해 전용 Bearer 인증으로 동작하도록 변경합니다. 관리자 요청의 CSRF를 끄거나 인증 미들웨어를 광범위하게 우회하지 않습니다. 누락·오류 키 거부와 관리자 로그인 쿠키가 있는 브라우저에서의 동작을 테스트합니다.

### 화면 이식

- `@attendance/attendance-react-scanner`를 설치하고 공개 컴포넌트와 CSS를 import합니다.
- `apps/web/src/pages/AttendanceScannerPage.tsx`에서 렌더링합니다.
- `apps/web/src/app/router.tsx`에 `/attendance/scanner` 경로를 등록합니다.
- 스캐너는 자체 인증 화면을 사용합니다. 일반 직원 로그인 래퍼를 필수로 적용하지 않습니다.
- 예제의 관리자 링크 `/`와 CSS는 MaruLog 구조에 맞춥니다.

장치 설정은 **USB-COM 또는 비상용 USB-KBW**입니다. 브라우저에서 USB-COM 포트를 선택하고 장치와 baud rate를 맞춥니다. KBW는 영문·Enter·입력창 포커스가 필요합니다. 근무지 모바일 URL 대신 회전 직원 QR을 읽습니다.

통신 오류 시 마지막 스캔은 서버에 저장되었을 수 있습니다. 화면 안내대로 관리자 기록을 먼저 확인하고 다시 연결합니다. 자동 재전송하지 않으며 전송하지 못한 대기 QR은 다시 읽습니다.

## 8. 관리자 화면과 모바일 선택 연결

관리자 화면에 다음 기능을 연결합니다.

- 기존 직원 선택 및 직원 QR 발급·재발급
- 출퇴근 현황과 출근 누락 표시
- 근무 규칙 적용일·출근 구간·정상 퇴근 경과 분 관리
- 보고된 특정 날짜의 13시 출근 예외
- 직원별 일회성 퇴근 모드 지정
- 승인 대기 처리·수동 수정·감사 이력

예제 `examples/web/main.tsx`를 기능 참조로 사용하되 MaruLog의 기존 직원 관리를 중복 생성하지 않습니다. 권장 관리자 경로는 `/admin/attendance`이며 서버에서도 ADMIN을 검사합니다.

모바일까지 연결할 때는 `/attendance/mobile` 경로, 해당 HTTPS 주소를 사용하는 `mobile_base_url`, 동의 문구·초대·기기 등록·GPS를 추가 검증합니다. 모바일 전용 토큰 요청과 관리자 세션 요청을 구분하고 쿠키·CSRF 충돌 여부를 확인합니다.

## 9. 테스트와 완료 기준

MaruLog 코드 지침에 따라 lint, typecheck, test, build를 모두 실행합니다. 테스트 DB 설정이 적용된 상태에서 수행하세요.

```sh
cd ~/Dev/MaruLog-attendance/apps/api
uv run ruff check .
uv run basedpyright
uv run pytest
uv run alembic current --check-heads
uv run alembic check

cd ~/Dev/MaruLog-attendance/apps/web
bun run lint
bun run typecheck
bun run test
bun run build
```

브라우저 E2E는 MaruLog의 기존 실행 설정을 확인해 독립 서버와 테스트 DB에서 실행합니다. 개발 API 포트는 8008을 사용하며 웹 프록시도 맞춥니다.

필수 검증표:

- [ ] wheel과 npm 파일을 포함한 Docker 이미지가 빌드된다.
- [ ] 기존 로그인·업무 기능이 정상이고 기존 데이터가 유지된다.
- [ ] 관리자만 직원 QR·근태·규칙·승인 API를 사용할 수 있다.
- [ ] CSRF 누락과 강제 비밀번호 변경 세션이 기존 규칙대로 차단된다.
- [ ] 스캐너 키 누락·오류는 거부되고 직원 비활성화가 스캔에 반영된다.
- [ ] 09:10:59 / 09:11:00 등 시간 경계가 예상대로 판정된다.
- [ ] 영상팀 날짜 예외가 해당 날짜에만 적용된다.
- [ ] 긴급 퇴근 모드는 지정만으로 기록되지 않고 다음 유효 스캔에 적용된다.
- [ ] 중복·연속 입력·빈 Enter·입력 포커스 이탈을 처리한다.
- [ ] 통신 단절·시간 초과 시 자동 재전송하지 않는다.
- [ ] 실제 USB 스캐너로 테스트 직원 QR을 읽고 DB와 관리자 화면에서 확인한다.
- [ ] 키·QR 원문이 로그나 브라우저 영구 저장소에 남지 않는다.
- [ ] PRD·UI·API 계약과 설치 문서를 구현 상태에 맞게 갱신한다.

패키지 검증 결과는 docs/implementation.md의 최신 기록을 확인합니다. 이는 MaruLog 통합 테스트나 실제 USB 장치 검증을 대신하지 않습니다.

## 10. 배포 및 복구

1. 검증한 커밋과 패키지 버전을 고정하고 새 이미지를 빌드합니다.
2. 운영 DB 백업·복구 가능 상태와 변경 전 migration revision을 확인합니다.
3. 출퇴근 설정과 스캐너 전용 키를 배포 환경에 등록합니다.
4. 기존 배포 절차에서 direct URL로 migration과 `check-migrations`를 실행합니다.
5. 검증된 이미지만 공유 8000 서비스에 배포합니다. 작업 중 공유 컨테이너를 교체하지 않습니다.
6. health/readiness, 기존 로그인, 출퇴근 관리자 권한과 스캐너 인증을 확인합니다.
7. 테스트용 직원 QR로 첫 실기 확인 후 실제 직원에게 발급합니다.

문제가 생기면 새 스캔을 중지하고 이전 이미지로 복구합니다. 추가한 출퇴근 테이블은 유지한 채 호환성을 확인하며, 운영에서 테이블을 삭제하는 downgrade를 실행하지 않습니다. 마이그레이션 상태 확인 도구는 새 테이블을 인식하는 버전을 사용합니다.

**자동 파기 작업은 이번 설치에 포함하지 않습니다.** MaruLog의 소프트 삭제 원칙과 출퇴근 패키지의 실제 파기 기능에 대한 적용 범위·보관 기간을 확정한 후 별도 연결합니다. Mac은 테스트용이며 자동 시작·절전 설정 변경도 이번 범위에 포함하지 않습니다.

## 11. 설치 완료 시 인계할 항목

- 반영 커밋, 이미지 태그, 패키지 버전과 migration revision
- 관리자·스캐너 페이지 주소
- 직원 매핑 및 비활성화 동기화 방식
- 적용 사업장과 근무 규칙·적용일
- 스캐너 키 보관 위치와 교체 방법 — 키 원문은 문서에 쓰지 않음
- 자동·실기 테스트 결과와 미완료 항목
- 장애 시 기록 확인·재스캔·이미지 복구 절차
