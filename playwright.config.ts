import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'tests/web',testMatch:'*.spec.ts',timeout:30000,fullyParallel:false,
  workers:1,reporter:'list',use:{baseURL:'http://127.0.0.1:5177',channel:process.env.CI ? undefined : 'chrome',headless:true,
    permissions:['geolocation'],geolocation:{latitude:37.5665,longitude:126.978},trace:'retain-on-failure'},
  webServer:[
    {command:'PYTHONPATH=python/attendance_core/src:python/attendance_fastapi/src:python/attendance_sqlalchemy/src:. .venv/bin/uvicorn tests.web.server:app --host 127.0.0.1 --port 8017',
     url:'http://127.0.0.1:8017/openapi.json',reuseExistingServer:false,
     env:{ATTENDANCE_ADMIN_TOKEN:'browser-test-admin',ATTENDANCE_SCANNER_TOKEN:'browser-test-scanner',ATTENDANCE_QR_SIGNING_SECRET:'browser-qr-signing-secret-at-least-32-bytes',ATTENDANCE_DATABASE_URL:`sqlite+aiosqlite:///./.browser-test-${process.pid}.db`,ATTENDANCE_MOBILE_URL:'http://127.0.0.1:5177/c'}},
    {command:'npm run dev',url:'http://127.0.0.1:5177',reuseExistingServer:false}
  ]});
