import {test, expect, type Page, type APIRequestContext} from '@playwright/test';

const headers={Authorization:'Bearer browser-test-admin'};
async function issue(request:APIRequestContext, name:string) {
  const employee=await (await request.post('/api/attendance/employees',{headers,data:{name}})).json();
  const qr=await (await request.get(`/api/attendance/employees/${employee.id}/qr`,{headers})).json();
  return {...employee, code:qr.code};
}
async function ready(page:Page) {
  await page.addInitScript(()=>{
    let stream:ReadableStreamDefaultController<Uint8Array>;
    const state={opened:[] as number[],closed:0,send:(s:string)=>stream.enqueue(new TextEncoder().encode(s)),unplug:()=>stream.error(new Error('unplugged'))};
    Object.assign(window,{serialTest:state});
    Object.defineProperty(navigator,'serial',{value:{requestPort:async()=>({
      readable:new ReadableStream<Uint8Array>({start(controller){stream=controller;}}),
      open:async({baudRate}:{baudRate:number})=>{state.opened.push(baudRate);},
      close:async()=>{state.closed++;},
    })}});
  });
  await page.goto('/scanner');
  await page.getByLabel('스캐너 접속 키').fill('browser-test-scanner');
  await page.getByRole('button',{name:'스캐너 연결',exact:true}).click();
  await page.getByLabel('통신 속도').selectOption('19200');
  await page.getByRole('button',{name:'USB-COM 포트 연결',exact:true}).click();
  await expect(page.getByRole('button',{name:'USB-COM 연결 해제'})).toBeVisible();
}
async function send(page:Page, data:string) {
  await page.evaluate(data=>(window as unknown as {serialTest:{send(s:string):void}}).serialTest.send(data),data);
}

test('USB-COM CR/LF 분할 수신, 150ms idle flush, 재사용 차단 및 수신 상태',async({page,request})=>{
  const first=await issue(request,'시리얼 직원 A');
  const second=await issue(request,'시리얼 직원 B');
  await ready(page);
  await send(page,first.code.slice(0,10));
  await send(page,first.code.slice(10)+'\r');
  await send(page,'\n'+second.code); // no terminator, idle flush
  await expect(page.getByRole('region',{name:'최근 스캔'}).getByText('시리얼 직원 A · 출근 완료')).toBeVisible();
  await expect(page.getByRole('region',{name:'최근 스캔'}).getByText('시리얼 직원 B · 출근 완료')).toBeVisible();
  await expect(page.getByText(/장치 데이터 \d+ byte 수신/)).toBeVisible();
  expect(await page.evaluate(()=>(window as unknown as {serialTest:{opened:number[]}}).serialTest.opened)).toEqual([19200]);
  await send(page,first.code+'\r\n');
  await expect(page.getByRole('status')).toContainText('이미 사용한 QR');
  await page.getByRole('button',{name:'USB-COM 연결 해제'}).click();
  await expect.poll(()=>page.evaluate(()=>(window as unknown as {serialTest:{closed:number}}).serialTest.closed)).toBe(1);
  await page.screenshot({path:'test-results/scanner-serial.png',fullPage:true});
});

test('과대 프레임의 뒷부분은 전송하지 않으며 다음 정상 프레임부터 수신',async({page,request})=>{
  const person=await issue(request,'프레임 검증');
  await ready(page);
  let requests=0;
  page.on('request',r=>{if(r.url().endsWith('/api/scanner/scans'))requests++;});
  await send(page,'x'.repeat(1025)+person.code+'\n'+person.code+'\r\n');
  await expect(page.getByRole('status')).toContainText('프레임 검증 · 출근 완료');
  expect(requests).toBe(1);
});

test('USB-COM 연결 해제는 미완성 프레임을 버린다',async({page,request})=>{
  const person=await issue(request,'해제 검증');
  await ready(page);
  let requests=0;
  page.on('request',r=>{if(r.url().endsWith('/api/scanner/scans'))requests++;});
  // Feed and click in the same JS task, before the 150 ms timer can fire.
  await page.evaluate(code=>{
    (window as unknown as {serialTest:{send(s:string):void}}).serialTest.send(code);
    const button=[...document.querySelectorAll('button')].find(b=>b.textContent==='USB-COM 연결 해제');
    button?.click();
  },person.code);
  await expect(page.getByRole('status')).toContainText('USB-COM 연결을 해제');
  await page.waitForTimeout(200); // exercise the cancelled hardware idle timer
  expect(requests).toBe(0);
});

test('포트 분리 안내 및 KBW 비상 입력',async({page,request})=>{
  const person=await issue(request,'비상 입력 직원');
  await ready(page);
  await page.evaluate(()=>(window as unknown as {serialTest:{unplug():void}}).serialTest.unplug());
  await expect(page.getByRole('status')).toContainText('USB-COM 연결이 끊겼습니다');
  await page.getByLabel('QR 스캔 입력').fill(person.code);
  await page.getByLabel('QR 스캔 입력').press('Enter');
  await expect(page.getByRole('status')).toContainText('비상 입력 직원 · 출근 완료');
});

test('대기열 10건 제한과 전송 결과 불확실 시 잔여 QR 폐기',async({page})=>{
  await ready(page);
  let attempts=0;
  let release:()=>void=()=>{};
  const gate=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/scanner/scans',async route=>{attempts++;await gate;await route.abort();});
  await send(page,Array.from({length:12},(_,i)=>`token-${i}`).join('\r\n')+'\r\n');
  await expect(page.getByRole('status')).toContainText('대기열이 가득');
  await expect(page.getByText(/처리 대기 11건/)).toBeVisible();
  release();
  await expect(page.getByRole('status')).toContainText('처리 여부 확인 필요');
  await expect(page.getByLabel('스캐너 접속 키')).toBeVisible();
  expect(attempts).toBe(1);
});

for(const failure of ['503','malformed'] as const) {
  test(`불확실한 서버 응답 ${failure}는 재전송하지 않는다`,async({page})=>{
    await ready(page);
    let attempts=0;
    await page.route('**/api/scanner/scans',async route=>{
      attempts++;
      await route.fulfill({status:failure==='503'?503:200,contentType:'application/json',body:JSON.stringify({message:'unexpected'})});
    });
    await send(page,'test-code\r\n');
    await expect(page.getByRole('status')).toContainText('처리 여부 확인 필요');
    await expect(page.getByLabel('스캐너 접속 키')).toBeVisible();
    expect(attempts).toBe(1);
  });
}
