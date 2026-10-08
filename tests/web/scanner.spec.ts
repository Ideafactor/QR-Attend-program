import {test,expect,type Page} from '@playwright/test';
const headers={Authorization:'Bearer browser-test-admin'};
async function connect(page:Page){
  await page.goto('/scanner');
  await page.getByLabel('스캐너 접속 키').fill('browser-test-scanner');
  await page.getByRole('button',{name:'스캐너 연결',exact:true}).click();
  await expect(page.getByLabel('QR 스캔 입력')).toBeFocused();
}
test('KBW 입력과 연속 스캔을 DB에 기록하고 빈 Enter는 무시한다',async({page,request})=>{
  const people=[];
  for(const name of ['스캐너 직원 A','스캐너 직원 B']){
    const response=await request.post('/api/attendance/employees',{headers,data:{name}});
    const person=await response.json();
    const issued=await request.get(`/api/attendance/employees/${person.id}/qr`,{headers});
    people.push({...person,qr_token:(await issued.json()).code});
  }
  await page.goto('/scanner');
  await page.getByLabel('스캐너 접속 키').fill('browser-test-admin');
  await page.getByRole('button',{name:'스캐너 연결',exact:true}).click();
  await expect(page.getByRole('status')).toHaveText('스캐너 접속 키를 확인하세요.');
  await connect(page);
  let posts=0;
  page.on('request',r=>{if(r.url().endsWith('/api/scanner/scans'))posts++;});
  for(const person of people){
    await page.getByLabel('QR 스캔 입력').pressSequentially(person.qr_token);
    await page.getByLabel('QR 스캔 입력').press('Enter');
  }
  await expect(page.getByRole('region',{name:'최근 스캔'}).getByText('스캐너 직원 B · 출근 완료')).toBeVisible();
  await page.getByLabel('QR 스캔 입력').press('Enter');
  expect(posts).toBe(2);
  for(const person of people){
    const rows=await (await request.get('/api/attendance/attendance?employee_id='+person.id,{headers})).json();
    expect(rows).toHaveLength(1);
  }
  await page.screenshot({path:'test-results/scanner.png',fullPage:true});
});
test('통신 실패 시 재전송하지 않고 확인 안내 후 연결 해제',async({page})=>{
  await connect(page);
  let posts=0;
  await page.route('**/api/scanner/scans',async route=>{posts++;await route.abort();});
  await page.getByLabel('QR 스캔 입력').fill('test-token');
  await page.getByLabel('QR 스캔 입력').press('Enter');
  await expect(page.getByRole('status')).toContainText('처리 여부 확인 필요');
  await expect(page.getByLabel('스캐너 접속 키')).toBeVisible();
  expect(posts).toBe(1);
});
