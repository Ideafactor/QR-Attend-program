import {test,expect, type APIRequestContext} from '@playwright/test';
const headers={Authorization:'Bearer browser-test-admin'};
const path='/api/attendance';
async function employee(request:APIRequestContext){
  const response=await request.post(path+'/employees',{headers,data:{name:'모바일 검증 '+Date.now()}});
  expect(response.status()).toBe(201);return response.json();
}
async function site(request:APIRequestContext){
  const response=await request.post(path+'/sites',{headers,data:{name:'서울 테스트 현장',lat:37.5665,lng:126.978,radius_m:200}});
  expect(response.status()).toBe(201);return response.json();
}

test('관리자 연결, 직원 등록, QR 표시, 모바일 초대',async({page})=>{
  await page.goto('/');
  await page.getByLabel('관리자 접속 키').fill('browser-test-admin');
  await page.getByRole('button',{name:'연결하기'}).click();
  await expect(page.getByRole('status')).toHaveText('연결했습니다.');
  await page.getByRole('button',{name:'직원·근무지'}).click();
  await page.getByRole('textbox',{name:'이름',exact:true}).fill('브라우저 등록 직원');
  await page.getByRole('button',{name:'직원 등록',exact:true}).click();
  await expect(page.getByRole('img',{name:'직원 사무실 QR'})).toBeVisible();
  await page.getByLabel('직원',{exact:true}).selectOption({label:'브라우저 등록 직원'});
  await page.getByRole('button',{name:'초대 링크 만들기'}).click();
  await expect(page.getByRole('heading',{name:'휴대폰 등록 링크'})).toBeVisible();
  await page.screenshot({path:'test-results/admin.png',fullPage:true});
});

test('동의·휴대폰 등록 → GPS 출근 → 관리자 일회성 퇴근',async({page,request})=>{
  const person=await employee(request);const location=await site(request);
  const invite=await (await request.post(path+`/employees/${person.id}/mobile-invite`,{headers})).json();
  await page.goto(`/c?invite=${invite.code}&t=${location.qr_token}`);
  await expect(page.getByRole('heading',{name:'휴대폰 등록'})).toBeVisible();
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'휴대폰 등록',exact:true}).click();
  await expect(page.getByRole('heading',{name:'서울 테스트 현장'})).toBeVisible();
  await page.getByRole('button',{name:'기록하기'}).click();
  await expect(page.getByRole('heading',{name:'출근 완료'})).toBeVisible();
  await expect(page.getByText('오전 9:00:00',{exact:true})).toBeVisible();
  const override=await request.put(path+`/employees/${person.id}/scan-override`,{headers,data:{label:'조퇴',reason:'긴급 병원 방문',expires_at:'2026-09-29T12:00:00+09:00'}});
  expect(override.status()).toBe(200);
  await page.reload();
  await page.getByRole('button',{name:'기록하기'}).click();
  await expect(page.getByRole('heading',{name:'조기 퇴근 기록'})).toBeVisible();
  const records=await (await request.get(path+`/attendance?employee_id=${person.id}`,{headers})).json();
  expect(records[0].label).toBe('조퇴');expect(records[0].protected).toBe(true);
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'test-results/mobile.png',fullPage:true});
});

test('위치 권한 거부 안내와 반경 밖 승인 대기',async({page,request})=>{
  const person=await employee(request);const location=await site(request);
  const invite=await (await request.post(path+`/employees/${person.id}/mobile-invite`,{headers})).json();
  const registration=await (await request.post(path+'/mobile/register',{data:{code:invite.code,consent:true,consent_version:'1'}})).json();
  await page.addInitScript(({token})=>{
    localStorage.setItem('attendance.mobile:/api/attendance',token);
    navigator.geolocation.getCurrentPosition=(_success,error)=>error?.({code:1,message:'denied',PERMISSION_DENIED:1,POSITION_UNAVAILABLE:2,TIMEOUT:3});
  },{token:registration.token});
  await page.goto(`/c?t=${location.qr_token}`);
  await expect(page.getByRole('heading',{name:'위치 권한을 켜 주세요.'})).toBeVisible();
  await expect(page.getByText(/iPhone: 설정/)).toBeVisible();
  const result=await request.post(path+'/mobile/checkins',{headers:{Authorization:'Bearer '+registration.token},data:{site_token:location.qr_token,lat:38,lng:127,accuracy:10}});
  expect(result.status()).toBe(200);expect((await result.json()).pending_reason).toBe('outside_geofence');
});

test('해제된 휴대폰은 새 초대 링크에서 다시 등록할 수 있다',async({page,request})=>{
  const person=await employee(request);
  const invite=await (await request.post(path+`/employees/${person.id}/mobile-invite`,{headers})).json();
  const registration=await (await request.post(path+'/mobile/register',{data:{code:invite.code,consent:true,consent_version:'1'}})).json();
  await page.goto('/c');
  await page.evaluate(token=>localStorage.setItem('attendance.mobile:/api/attendance',token),registration.token);
  expect((await request.delete(path+`/employees/${person.id}/mobile-device`,{headers})).status()).toBe(200);
  const next=await (await request.post(path+`/employees/${person.id}/mobile-invite`,{headers})).json();
  await page.goto('/c?invite='+next.code);
  await expect(page.getByRole('heading',{name:'휴대폰 등록'})).toBeVisible();
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'휴대폰 등록',exact:true}).click();
  await expect(page.getByText('등록되었습니다. 근무지 QR을 스캔해 주세요.')).toBeVisible();
});

test('잘못된 근무지 QR은 등록된 휴대폰 토큰을 지우지 않는다',async({page,request})=>{
  const person=await employee(request);
  const invite=await (await request.post(path+`/employees/${person.id}/mobile-invite`,{headers})).json();
  const registration=await (await request.post(path+'/mobile/register',{data:{code:invite.code,consent:true,consent_version:'1'}})).json();
  const location=await (await request.post(path+'/sites',{headers,data:{name:'회전 QR 현장',lat:37.5665,lng:126.978,qr_mode:'rotating'}})).json();
  await page.goto('/c');
  await page.evaluate(token=>localStorage.setItem('attendance.mobile:/api/attendance',token),registration.token);
  await page.goto(`/c?t=${location.id}.1.invalid-signature`);
  await expect(page.getByRole('alert')).toHaveText('QR 또는 초대 링크가 유효하지 않습니다. 관리자에게 새 링크를 요청하세요.');
  expect(await page.evaluate(()=>localStorage.getItem('attendance.mobile:/api/attendance'))).toBe(registration.token);
});
