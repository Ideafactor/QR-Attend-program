# QR Attend Program

FastAPI 기반 QR 출퇴근 관리 패키지입니다. 기존 서비스에 Python API와 SQLAlchemy 저장소를 연결하고, React 모바일 체크인·USB 스캐너 화면을 선택해서 사용할 수 있습니다.

현재 패키지 버전은 **0.2.0**입니다. Python 패키지 3개와 npm 패키지 3개를 함께 관리하며, 레지스트리 게시 없이 소스 또는 직접 만든 배포 번들로 설치합니다. 관리자 화면은 호스트에서 구현하며 `examples/web`은 연동 확인용 예제입니다.

## 문서 안내

- [스캐너 페이지](#스캐너-페이지): 화면 미리보기, 접속 주소와 USB 연결 방법

- [범용 설치 매뉴얼](docs/install.md): 기존 서비스 설치, 스캐너 연결, 0.1.x 업그레이드
- [구현 현황](docs/implementation.md): 구현 범위와 제약, PRD와의 차이
- [요구사항](docs/prd.md) · [OpenAPI 명세](docs/openapi.json)

## 프로젝트 구성

| 경로 | 역할 |
| --- | --- |
| `python/attendance_core` | 출퇴근 판정 규칙과 QR 처리 |
| `python/attendance_fastapi` | 관리자·모바일·직원·스캐너 API |
| `python/attendance_sqlalchemy` | SQLAlchemy 저장소와 Alembic 마이그레이션 |
| `js/attendance-client` | TypeScript API 클라이언트와 생성 타입 |
| `js/attendance-react-mobile` | 모바일 체크인 화면과 훅 |
| `js/attendance-react-scanner` | USB-COM / USB-KBW 스캐너 화면 |
| `examples` | FastAPI·React 연동 예제와 초기 근무 규칙 |
| `scripts` | 마이그레이션, 보관 기한 파기, 명세·배포 빌드 |
| `tests` | Python·클라이언트·브라우저 테스트 |

## 주요 기능

- 30분 출근 구간 + 10분 인정 여유. 09:10:59까지 09:00, 09:11부터 09:30 인정.
- 실제 출근·인정 출근을 별도로 보존하고 정상 퇴근은 인정 출근 + 설정된 경과 분으로 계산. 테스트 장소는 540분.
- 날짜 예외 → 직원 → 팀·포지션 → 외부 근무지 → 회사 기본 규칙. 영상팀 13시 출근은 보고된 날짜에만 배정.
- 예정 퇴근 전 재스캔은 already_in. 활성 일회성 퇴근 지정만 조기 퇴근 허용. 최초 출근·최신 정상 퇴근 집계, 출근 누락 표시, 관리자 일회성 퇴근 모드, 승인 및 수동 수정 보호.
- 60초 서버 서명 직원 QR·원자적 재사용 차단·본인 상태 조회, QR 재발급, 모바일 일회용 초대·동의·기기 등록·해제·토큰 갱신, GPS 반경·정확도 검증, 고정·30초 회전 QR.
- 근무 규칙 버전·스냅샷·재판정, CSV, 감사 로그, 보관 기간 파기·법적 보류.
- SQLAlchemy 저장소, Alembic 초기 마이그레이션, OpenAPI 기반 TypeScript 타입, 헤드리스 훅과 커스텀 가능한 모바일 화면.

## 빠른 실행

Python 3.11 이상(검증: 3.13), Node.js 22.12 이상, npm과 uv가 필요합니다. 아래 셸 명령은 macOS/Linux 기준입니다.

```sh
git clone https://github.com/Ideafactor/QR-Attend-program.git
cd QR-Attend-program
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
npm ci
npm run build
```

API와 웹을 각각 별도 터미널에서 실행합니다. 아래 접속 키는 본인이 정합니다.

```sh
export ATTENDANCE_ADMIN_TOKEN='로컬에서-사용할-접속-키'
export ATTENDANCE_QR_SIGNING_SECRET='replace-with-a-random-secret-at-least-32-bytes'
export ATTENDANCE_SCANNER_TOKEN='관리자와-다른-스캐너-전용-접속-키'
.venv/bin/python -m uvicorn examples.app:app --host 127.0.0.1 --port 8017
```

```sh
npm run dev
```

- 관리자 예제: http://localhost:5177
- 모바일 화면: http://localhost:5177/c
- USB-COM / USB-KBW 스캐너 화면: http://localhost:5177/scanner
- API 문서: http://127.0.0.1:8017/docs

관리자 화면에 동일한 접속 키를 입력합니다. 직원 추가 → 휴대폰 초대 → 초대 링크에서 동의·등록 → 근무지 QR 링크에서 체크 순서로 확인합니다. 사무실 직원 QR은 60초마다 만료되므로 직원 화면에서 갱신합니다. 관리자 예제의 단일 QR 표시는 단기 테스트용입니다.

`localhost`와 `127.0.0.1`은 서로 다른 브라우저 저장소입니다. 같은 주소를 일관되게 사용하세요. 실제 휴대폰은 HTTPS 호스트 주소와 `ATTENDANCE_MOBILE_URL`을 설정해야 합니다. 브라우저 위치 권한은 체크할 때만 요청합니다.

예제는 SQLite `attendance.db`에 저장합니다. 서버 재시작 시 기존 DB 규칙을 초기 파일로 덮어쓰지 않습니다. [초기 시간표](examples/work-rule.json)는 최초 DB 규칙 등록에만 사용합니다.

## 환경 변수

아래는 `examples/app.py` 기준 설정입니다. 접속 키와 서명 비밀값은 환경 변수로 전달합니다.

| 변수 | 용도 / 기본값 |
| --- | --- |
| `ATTENDANCE_ADMIN_TOKEN` | 관리자 예제 접속 키 |
| `ATTENDANCE_SCANNER_TOKEN` | 스캐너 전용 접속 키 |
| `ATTENDANCE_QR_SIGNING_SECRET` | 직원 QR 서명용 비밀값(32바이트 이상) |
| `ATTENDANCE_DATABASE_URL` | 기본값 `sqlite+aiosqlite:///./attendance.db` |
| `ATTENDANCE_MOBILE_URL` | 기본값 `http://localhost:5177/c`; 휴대폰 테스트 시 HTTPS 주소 |
| `ATTENDANCE_EMPLOYEE_TOKEN` | 직원 본인 QR 발급 API 예제 인증 키 |
| `ATTENDANCE_EMPLOYEE_ID` | 위 인증 키에 연결할 직원 ID |
| `ATTENDANCE_TEST_DATABASE_URL` | PostgreSQL 테스트용 별도 DB 주소 |

직원 인증 키와 직원 ID의 고정 매핑은 예제용입니다. 실제 서비스에서는 로그인한 직원의 세션으로 본인을 확인합니다.

## 스캐너 페이지

스캐너를 연결한 PC에서 여는 **출퇴근 접수용 페이지**입니다. USB 포트 연결, 통신 속도 설정, 장치 수신 상태, 출퇴근 처리 결과와 최근 10건을 한 화면에서 확인할 수 있습니다.

![스캐너 페이지: USB-COM 연결 설정, 장치 수신 상태와 최근 출퇴근 기록](docs/images/scanner-page.png)

*예제 브라우저 테스트에서 모의 USB-COM 장치로 두 건을 처리한 뒤 포트 연결을 해제한 화면입니다. 실제 장비 연결을 촬영한 화면은 아닙니다.*

### 로컬에서 열기

[빠른 실행](#빠른-실행)에 따라 API와 웹 서버를 실행한 뒤, 스캐너를 꽂은 PC에서 **[http://localhost:5177/scanner](http://localhost:5177/scanner)** 를 엽니다. 관리자 예제의 **USB QR 스캐너** 링크로도 이동할 수 있습니다.

1. 서버에 설정한 `ATTENDANCE_SCANNER_TOKEN`을 **스캐너 접속 키**에 입력하고 **스캐너 연결**을 누릅니다.
2. USB-COM 장치는 통신 속도를 장치 설정과 맞춘 뒤 **USB-COM 포트 연결**을 눌러 포트를 선택합니다. Web Serial을 지원하는 데스크톱 Chrome/Edge의 HTTPS 또는 localhost 환경에서 사용합니다.
3. USB-KBW(키보드 입력) 장치는 **입력창 활성화**를 누른 뒤 사용합니다. 키보드는 영문 입력, 스캐너 종료 문자는 Enter로 설정합니다.
4. 인증된 직원 화면에서 발급한 **60초 회전 직원 QR**을 스캔하고 처리 결과를 확인합니다. 임의 테스트 QR이나 근무지 모바일 URL은 직원 출퇴근 QR로 처리하지 않습니다.

스캐너 전용 키를 통한 서버 인증과 USB-COM 포트 연결은 별도 단계입니다. 페이지를 새로고침하면 다시 연결해야 합니다.

### 실제 서비스에 연결

공통 화면은 [`AttendanceScanner`](js/attendance-react-scanner/src/index.tsx)로 제공하고, [`examples/web/scanner.tsx`](examples/web/scanner.tsx)는 이를 사용하는 예제입니다. 실제 서비스에서는 이 컴포넌트를 서비스의 페이지 경로에 등록하고 스캐너 API에 연결합니다. 연동 후에는 해당 서비스의 스캐너 페이지를 사용하므로 이 저장소의 예제 웹 서버를 별도로 실행할 필요가 없습니다.

```tsx
import { AttendanceScanner } from '@attendance/attendance-react-scanner';
import '@attendance/attendance-react-scanner/style.css';

export function ScannerPage() {
  return <AttendanceScanner baseUrl="/api/scanner" title="사무실 QR 스캐너" />;
}
```

페이지 경로(예: `/scanner`)는 호스트의 웹 라우터에 등록하고, `baseUrl`은 서버 스캐너 API의 경로와 맞춥니다.

설치 방법은 [범용 설치 매뉴얼](docs/install.md)을 따릅니다.

- 서버: `attendance_fastapi.create_scanner_router(attendance, token=..., prefix="/api/scanner")`를 명시적으로 등록합니다.
- 화면: `@attendance/attendance-react-scanner`의 `AttendanceScanner`와 스타일을 불러옵니다. baseUrl로 서버 경로를 지정합니다.
- 예제의 `examples/kbw.py`와 `examples/web/scanner.tsx`는 공개 패키지를 사용하는 얇은 연결 코드입니다.

기본 관리자 라우터에 스캐너 경로가 자동으로 추가되지는 않습니다. 서버 내부에서 `record_scan()`을 호출하며, 사업장은 `tenant_id`로 고정합니다. 클라이언트는 사업장·직원 ID·시각·출퇴근 모드를 지정할 수 없습니다. 운영에서는 HTTPS와 별도 스캐너 키를 사용합니다.

입력창은 연속 QR을 순서대로 전송하며 대기열은 최대 10개입니다. 처리 결과와 최근 10건을 표시하고 빈 Enter는 무시합니다. 접속 키와 QR 원문은 브라우저 저장소에 보관하지 않으며 새로고침하면 다시 연결합니다. 통신 오류·시간 초과·서버 오류는 이미 저장되었을 가능성이 있으므로 자동 재시도하지 않습니다. 관리자 기록을 확인한 후 다시 연결하고, 전송되지 않은 대기 QR을 다시 읽으세요.

Mac은 테스트용이며 자동 시작이나 전원 설정은 변경하지 않았습니다. 실제 스캐너의 종료 문자·입력 언어·포커스 유지와 운영 PC 환경은 현장에서 확인해야 합니다.

0.1.x에서 올릴 때는 [0.2.0 업그레이드 절차](docs/install.md#7-01x--020-업그레이드-필수)를 먼저 확인하세요. 기본 QR 형식과 DB 테이블이 변경됩니다.

## 호스트 연동

```python
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from attendance_core import Rules
from attendance_fastapi import AttendanceConfig, Hooks, create_attendance
from attendance_sqlalchemy import SqlAlchemyRepository

engine = create_async_engine(database_url)
attendance = create_attendance(
    repository=SqlAlchemyRepository(async_sessionmaker(engine, expire_on_commit=False)),
    config=AttendanceConfig(rules=Rules(), mobile_base_url='https://example.com/c'),
    hooks=Hooks(on_recorded=notify_employee),
    # 다중 회사에서는 인증된 요청 컨텍스트에서 회사 ID를 반환하세요.
    tenant_resolver=resolve_tenant,
)
app = FastAPI()
app.include_router(attendance.router(admin_dependency=require_admin), prefix='/api/attendance')

# 사무실 스캔은 HTTP 엔드포인트 없이 호스트 내부에서 호출합니다.
result = await attendance.record_scan(code=employee_qr, source='kiosk', tenant_id=company_id)
```

관리자 의존성은 관리자 ID를 반환하며 `None`/`False`는 403입니다. `tenant_resolver`는 호스트가 신뢰할 수 있는 회사 ID를 반환해야 합니다. 직접 `record_scan()` 호출은 반드시 해당 `tenant_id`를 넘깁니다(단일 회사 기본값은 `default`). 휴대폰·현장 태블릿 토큰은 관리자 권한을 제공하지 않습니다.

훅은 DB 커밋 후 호출합니다. `on_recorded`/`on_pending` 이벤트에는 `employee.id`, `employee.host_user_id`, `result` 등이 있습니다. 알림 채널은 호스트가 연결하며 훅 실패는 기록을 롤백하지 않고 로그에 남습니다. 내구성 있는 재전송이 필요하면 호스트의 메시지 큐를 사용하세요.

```tsx
import { createAttendanceClient } from '@attendance/attendance-client';
import { MobileCheckIn } from '@attendance/attendance-react-mobile';

const client = createAttendanceClient({ baseUrl: '/api/attendance', fetcher: adminFetch });
// client는 렌더마다 재생성하지 말고 모듈 범위 또는 useMemo에서 생성하세요.
<MobileCheckIn client={client} companyName="회사 이름" />
```

`fetcher`는 관리자용, `mobileFetcher`는 모바일용입니다. 모바일 토큰은 기본적으로 localStorage에 저장하며 `tokenStore`로 교체할 수 있습니다. 다중 회사는 회사별 저장소 키를 사용하세요. 테마·문구·슬롯을 바꾸거나 `useCheckIn({ client, siteToken })`만 사용할 수 있습니다.

## PostgreSQL / 마이그레이션

```sh
export ATTENDANCE_DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST/DB'
.venv/bin/python -m scripts.migrate
```

호스트 Alembic에 통합할 때 `version_locations`에 다음 경로를 추가하고 `attendance@head`를 적용합니다.

```python
from pathlib import Path
import attendance_sqlalchemy
migration_path = Path(attendance_sqlalchemy.__file__).parent / 'migrations' / 'versions'
```

`create_schema()`는 개발용입니다. 운영 호스트는 Alembic으로 버전을 관리합니다. 현재 마이그레이션 체인은 `att_0001 → att_0002`이며 모든 테이블에 `att_` 접두사를 사용합니다. 날짜와 시각은 SQL Date/TIMESTAMPTZ 컬럼, 확장 필드는 JSON에 저장합니다. JSON과 검색용 컬럼은 저장소가 한 트랜잭션에서 같이 갱신하므로 테이블을 직접 수정하지 마세요.

직원·날짜 유일성 제약과 테넌트별 트랜잭션 잠금으로 중복 기록·초대 이중 사용·일회성 모드 중복 소비를 막습니다. 현재 구현은 테넌트 내 요청을 직렬화하고 일부 조회는 전체 목록을 읽습니다. 대규모 배포 전에는 실제 부하에 맞춰 페이지네이션·필터 조회와 잠금 범위를 확장해야 합니다.

## 일회성 퇴근 / 영상팀 예외

- `PUT /employees/{id}/scan-override`: `mode: "out"`, `label`, `reason`, `expires_at` 지정. 지정만으로 기록하지 않고 다음 유효 스캔에 한 번 적용됩니다.
- 잘못된 QR·중복 스캔에는 모드를 소비하지 않습니다. 위치 검증 대기이면 스캔에 퇴근 의도를 연결해 소비하고 관리자 승인을 기다립니다.
- 확정한 퇴근은 보호됩니다. 복귀·재근무 시에는 관리자 수정 API로 변경합니다.
- 영상팀용 별도 규칙을 만든 뒤 `PUT /employees/{id}/rule-exception`에 `rule_id`, `date`, `reason`을 전달합니다.
- 범위 밖 첫 출근은 기본 승인 대기, 출근 없이 18시 이후 스캔은 기본 출근 누락 퇴근입니다. 두 기준 모두 DB에서 바꿀 수 있습니다. 영상팀 예외의 인정 여유와 출근 누락 경계도 해당 규칙에 지정합니다.

## 보관 기간과 실행 작업

```sh
.venv/bin/python -m scripts.purge --tenant default
```

호스트의 cron/작업 스케줄러에서 매일 한 번 실행합니다. 이 명령은 설정된 보관 기한이 지난 데이터를 실제로 파기합니다. `legal_hold`는 해당 직원의 기록·GPS·초대 파기를 막습니다. GPS는 스캔과 승인 감사 스냅샷에서 함께 지우고 거리·결과를 남깁니다.

브라우저 USB-COM은 React 스캐너의 Web Serial로 연결합니다. 서버에 직접 붙이는 선택적 시리얼 수신 예제는 [examples/scanner.py](examples/scanner.py)를 호스트 FastAPI lifespan에서 백그라운드 작업으로 실행합니다. 별도로 `pyserial`이 필요합니다. CR 종료, 부분 수신, 장치 재연결을 처리하지만 USB 장비 실기·Mac 재부팅 자동 실행·알림 채널은 호스트 환경에서 확인해야 합니다.

## 검증과 빌드

```sh
.venv/bin/ruff check python tests examples scripts
.venv/bin/pytest -q
ATTENDANCE_TEST_DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST/TEST_DB' .venv/bin/pytest -q
.venv/bin/python -m scripts.export_openapi
npm run generate:types
npm run build
npm run build:example
npm run test:client
npm run test:web
.venv/bin/python -m build --no-isolation python/attendance_core
.venv/bin/python -m build --no-isolation python/attendance_fastapi
.venv/bin/python -m build --no-isolation python/attendance_sqlalchemy
```

PostgreSQL 테스트는 테스트별 임시 스키마를 만들고 지웁니다. 테스트 DB 사용자에게 CREATE SCHEMA 권한이 필요합니다. 브라우저 테스트는 로컬 Chrome을 사용하고 8017/5177 포트를 직접 실행하므로 기존 예제 서버를 먼저 종료합니다. CI에서는 Playwright Chromium을 사용합니다.

Python 패키지 3개와 npm 패키지 3개의 호환 버전은 모두 `0.2.0`입니다. 레지스트리 게시와 운영 배포는 하지 않았습니다. 초기 개발 버전이며 자세한 구현 상태와 PRD 차이는 [구현 현황](docs/implementation.md)을 참고하세요.

## 배포 번들 만들기

개발 의존성을 설치한 뒤 저장소 루트에서 실행합니다.

```sh
.venv/bin/python -m scripts.build_release
.venv/bin/python -m scripts.verify_release
```

`dist/attendance-0.2.0-bundle.tar.gz`에 Python wheel·sdist, npm tgz, 독립 실행 예제, 설치 문서와 체크섬이 생성됩니다. 검증 스크립트는 격리된 환경에 패키지를 설치하므로 uv와 외부 의존성을 받을 네트워크가 필요합니다. `dist/`는 Git에 포함되지 않습니다. 생성한 번들의 설치는 [설치 매뉴얼](docs/install.md)을 따릅니다.
