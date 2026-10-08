"""Install built files in isolated projects and exercise the public API."""

from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "dist/attendance-0.2.0"


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True)


with tempfile.TemporaryDirectory(prefix="attendance-install-") as directory:
    work = Path(directory)
    run("uv", "venv", str(work / "venv"), cwd=work)
    python = str(work / "venv/bin/python")
    run(
        "uv",
        "pip",
        "install",
        "--python",
        python,
        "--find-links",
        str(RELEASE),
        "attendance-core==0.2.0",
        "attendance-fastapi==0.2.0",
        "attendance-sqlalchemy[sqlite]==0.2.0",
        "httpx",
        cwd=work,
    )
    run(
        python,
        "-c",
        """
import asyncio
from importlib.metadata import version
from importlib import import_module
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from attendance_fastapi import AttendanceConfig, create_attendance, create_scanner_router
from attendance_sqlalchemy import SqlAlchemyRepository
async def main():
    engine=create_async_engine('sqlite+aiosqlite:///test.db')
    repo=SqlAlchemyRepository(async_sessionmaker(engine,expire_on_commit=False))
    await repo.create_schema(engine)
    service=create_attendance(repo, config=AttendanceConfig(qr_signing_secret="isolated-install-signing-secret-32-bytes"))
    app=FastAPI()
    app.include_router(service.router(lambda:'installer'),prefix='/attendance')
    app.include_router(create_scanner_router(service,token=lambda:'test-key',prefix='/clock'))
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        employee=await client.post('/attendance/employees',json={'name':'Install test'})
        assert employee.status_code==201, employee.text
        code=(await service.issue_employee_qr(employee.json()['id']))['code']
        result=await client.post('/clock/scans',headers={'Authorization':'Bearer test-key'},json={'code':code})
        assert result.status_code==200, result.text
        again=await client.post('/clock/scans',headers={'Authorization':'Bearer test-key'},json={'code':code})
        assert again.status_code==409, again.text
        assert import_module('attendance_sqlalchemy.migrations.versions.0002_rotating_qr').revision=='att_0002'
    await engine.dispose()
    assert version('attendance-fastapi')=='0.2.0'
asyncio.run(main())
print('Isolated wheel API/SQLite smoke test passed')
""",
        cwd=work,
    )
    (work / "package.json").write_text('{"private":true,"type":"module"}')
    packages = sorted(str(p) for p in RELEASE.glob("*.tgz"))
    run("npm", "install", "--ignore-scripts", *packages, "react@19", "react-dom@19", cwd=work)
    run(
        "node",
        "--input-type=module",
        "-e",
        """
import {createElement} from 'react';
import {renderToString} from 'react-dom/server';
import {AttendanceScanner} from '@attendance/attendance-react-scanner';
import {MobileCheckIn} from '@attendance/attendance-react-mobile';
import {createAttendanceClient} from '@attendance/attendance-client';
import {existsSync} from 'node:fs';
if (!renderToString(createElement(AttendanceScanner,{baseUrl:'/custom'})).includes('QR')) throw Error('render');
if (!existsSync(import.meta.resolve('@attendance/attendance-react-scanner/style.css').replace('file://',''))) throw Error('css');
if(typeof MobileCheckIn!=='function'||typeof createAttendanceClient!=='function') throw Error('exports');
console.log('Isolated npm exports/CSS/server-render smoke test passed');
""",
        cwd=work,
    )
print("Release installation verified")
