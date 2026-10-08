import {StrictMode, useCallback, useEffect, useMemo, useState, type FormEvent} from 'react';
import {createRoot} from 'react-dom/client';
import {createAttendanceClient, type AttendanceRecord, type RuleInput} from '@attendance/attendance-client';
import {MobileCheckIn} from '@attendance/attendance-react-mobile';
import './style.css';
import {Scanner} from './scanner';

type Employee = {id:string;name:string;active:boolean};
type Site = {id:string;name:string;radius_m:number;qr_mode:string};
type Rule = {id:string;group_id:string;name:string;effective_from:string;is_default:boolean;values:Omit<RuleInput,'name'|'effective_from'|'is_default'>};
type Pending = {id:string;employee_id:string;scanned_at:string;pending_reason:string;override_id?:string};
type Audit = {id:string;actor_id:string;target_table:string;created_at:string};
const today = () => new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Seoul'});
const time = (value?:string|null) => value ? new Date(value).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';
const readForm = (event:FormEvent<HTMLFormElement>) => {event.preventDefault();return new FormData(event.currentTarget);};
const field = (data:FormData,key:string) => String(data.get(key) ?? '');

function Admin() {
  const [auth,setAuth] = useState(()=>sessionStorage.getItem('attendance.example.admin') ?? '');
  const [connected,setConnected] = useState(false);
  const [tab,setTab] = useState('현황');
  const [employees,setEmployees] = useState<Employee[]>([]);
  const [records,setRecords] = useState<AttendanceRecord[]>([]);
  const [sites,setSites] = useState<Site[]>([]);
  const [rules,setRules] = useState<Rule[]>([]);
  const [pending,setPending] = useState<Pending[]>([]);
  const [audits,setAudits] = useState<Audit[]>([]);
  const [message,setMessage] = useState('');
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const [link,setLink] = useState<{title:string;url:string}>();
  const [qr,setQr] = useState<string>();
  const client = useMemo(()=>createAttendanceClient({baseUrl:'/api/attendance',fetcher:(input,init)=>{
    const headers=new Headers(init?.headers);headers.set('Authorization','Bearer '+auth);
    return fetch(input,{...init,headers});
  }}),[auth]);
  const refresh = useCallback(async()=>{
    const [people,days,locations,policies,waiting,history] = await Promise.all([
      client.admin.getEmployees(),client.admin.getAttendance({date:today()}),
      client.admin.request<Site[]>('/sites'),client.admin.request<Rule[]>('/work-rules'),
      client.admin.request<Pending[]>('/pending'),client.admin.request<Audit[]>('/audit-logs')]);
    setEmployees(people);setRecords(days);setSites(locations);setRules(policies);
    setPending(waiting);setAudits(history);setConnected(true);
  },[client]);
  const run = async(action:()=>Promise<unknown>,success='저장했습니다.')=>{
    setBusy(true);setError('');setMessage('');
    try {await action();await refresh();setMessage(success);} catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  useEffect(()=>{return ()=>{if(qr)URL.revokeObjectURL(qr);};},[qr]);
  const displayQR = async(value:string)=>{
    const response=await fetch('/api/attendance/qr/render',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+auth},body:JSON.stringify({code:value})});
    if(!response.ok)throw new Error('QR을 만들지 못했습니다.');
    setQr(URL.createObjectURL(await response.blob()));
  };
  const selectEmployee = <select aria-label="직원" name="employee" required defaultValue=""><option value="" disabled>직원 선택</option>{employees.map(e=><option key={e.id} value={e.id}>{e.name}</option>)}</select>;
  return <div className="app-shell"><aside><a className="brand" href="/">◷ <span>출퇴근 관리</span></a><p className="caption">ATTENDANCE / EXAMPLE</p>
    <nav aria-label="관리 메뉴">{['현황','직원·근무지','근무 규칙','승인·이력'].map(name=><button key={name} className={tab===name?'selected':''} onClick={()=>setTab(name)}>{name}<span>↗</span></button>)}</nav>
    <div className="sidebar-note"><span className="dot"/>테스트 장소<p>09:00–11:00 · 30분 간격<br/>인정 출근 + 9시간</p><a href="/c">직원 모바일 화면 ↗</a><br/><a href="/scanner">USB QR 스캐너 ↗</a></div></aside>
    <main className="workspace"><header className="topbar"><span>WORKSPACE / {tab}</span><time>{today()}</time></header>
      <div className="heading"><div><p className="eyebrow">하루의 시작부터 마무리까지</p><h1>{tab}</h1></div>{connected&&<button className="secondary" disabled={busy} onClick={()=>void run(refresh,'새로고침했습니다.')}>새로고침</button>}</div>
      {!connected&&<section className="panel connect"><h2>관리자 연결</h2><p>예제 서버에 설정한 관리자 접속 키를 입력하세요.</p><form onSubmit={e=>{e.preventDefault();sessionStorage.setItem('attendance.example.admin',auth);void run(refresh,'연결했습니다.');}}>
        <label>관리자 접속 키<input type="password" value={auth} onChange={e=>setAuth(e.target.value)} required autoComplete="off"/></label><button disabled={busy}>연결하기</button></form></section>}
      {error&&<div role="alert" className="notice error">{error}</div>}{message&&<div role="status" className="notice">{message}</div>}
      {connected&&tab==='현황'&&<><div className="stats"><article><span>등록 직원</span><strong>{employees.filter(e=>e.active).length}<small>명</small></strong></article><article><span>오늘 출근</span><strong>{records.filter(r=>r.in_at).length}<small>명</small></strong></article><article><span>오늘 퇴근</span><strong>{records.filter(r=>r.out_at).length}<small>명</small></strong></article><article><span>승인 대기</span><strong>{pending.length}<small>건</small></strong></article></div>
        <section className="panel"><div className="panel-title"><h2>오늘의 기록</h2><span className="muted">실제 시각과 인정 시각을 함께 확인하세요</span></div><div className="table-scroll"><table><thead><tr><th>직원</th><th>실제 출근</th><th>인정 출근</th><th>정상 퇴근 기준</th><th>퇴근</th><th>상태</th></tr></thead><tbody>{records.map(r=><tr key={r.id}><td>{employees.find(e=>e.id===r.employee_id)?.name??r.employee_id}</td><td>{time(r.in_at)}</td><td>{time(r.credited_in_at)}</td><td>{time(r.expected_out_at)}</td><td>{time(r.out_at)}</td><td><span className="pill">{r.label??(!r.in_at?'출근 누락':r.protected?'관리자 확정':r.out_kind==='early'?'조기 퇴근':r.out_at?'퇴근 기록':'출근 기록')}</span></td></tr>)}</tbody></table></div>{!records.length&&<p className="empty">아직 오늘 기록이 없습니다. 직원의 QR 스캔이 들어오면 표시됩니다.</p>}</section>
        <section className="panel"><h2>일회성 퇴근 모드</h2><p className="muted">급한 조퇴·휴가 시 지정하세요. 해당 직원의 다음 유효 스캔 한 번에 적용됩니다.</p><form className="form-grid" onSubmit={e=>{const data=readForm(e);void run(()=>client.admin.setScanOverride(field(data,'employee'),{mode:'out',label:field(data,'label') as '조퇴'|'휴가'|'기타',reason:field(data,'reason'),expires_at:new Date(field(data,'expires')).toISOString()}),'다음 스캔의 퇴근 모드를 지정했습니다.');}}>
          <label>직원{selectEmployee}</label><label>구분<select name="label"><option>조퇴</option><option>휴가</option><option>기타</option></select></label><label>만료 시각<input name="expires" type="datetime-local" required/></label><label>사유<input name="reason" required placeholder="병원 방문 등"/></label><button disabled={busy}>퇴근 모드 지정</button></form></section></>}
      {connected&&tab==='직원·근무지'&&<><div className="two-columns"><section className="panel"><h2>직원 추가</h2><form onSubmit={e=>{const data=readForm(e);void run(async()=>{const person=await client.admin.createEmployee({name:field(data,'name')});await displayQR((await client.admin.issueEmployeeQr(person.id)).code);setLink(undefined);},'직원을 등록했습니다. 사무실 QR은 60초 단위로 만료됩니다.');}}><label>이름<input name="name" placeholder="직원 이름" required/></label><button disabled={busy}>직원 등록</button></form></section>
        <section className="panel"><h2>휴대폰 초대</h2><form onSubmit={e=>{const data=readForm(e);void run(async()=>{const invite=await client.admin.inviteMobile(field(data,'employee'));setLink({title:'휴대폰 등록 링크',url:invite.invite_url});await displayQR(invite.invite_url);},'24시간 동안 유효한 초대 링크를 만들었습니다.');}}><label>직원{selectEmployee}</label><button disabled={busy}>초대 링크 만들기</button></form></section></div>
        <section className="panel"><h2>근무지 등록</h2><form className="form-grid" onSubmit={e=>{const data=readForm(e);void run(async()=>{const site=await client.admin.request<{check_url:string}>('/sites','POST',{name:field(data,'name'),lat:Number(field(data,'lat')),lng:Number(field(data,'lng')),radius_m:Number(field(data,'radius'))});setLink({title:'근무지 체크 링크',url:site.check_url});await displayQR(site.check_url);},'근무지 QR을 만들었습니다.');}}>
          <label>근무지 이름<input name="name" required placeholder="본사"/></label><label>위도<input name="lat" type="number" step="any" min="-90" max="90" defaultValue="37.5665" required/></label><label>경도<input name="lng" type="number" step="any" min="-180" max="180" defaultValue="126.978" required/></label><label>허용 반경 (m)<input name="radius" type="number" min="1" defaultValue="200" required/></label><button disabled={busy}>근무지 등록</button></form></section>
        {(qr||link)&&<section className="panel qr-result"><div><h2>{link?.title??'직원 사무실 QR'}</h2>{link&&<a href={link.url}>{link.url}</a>}<p className="muted">발급 시에만 제공되는 QR입니다. 저장하지 못했다면 재발급하세요.</p>{qr&&<a className="download" href={qr} download="attendance-qr.svg">QR 저장 ↓</a>}</div>{qr&&<img src={qr} width={200} height={200} alt={link?.title??'직원 사무실 QR'}/>}</section>}
        <section className="panel"><h2>등록 목록</h2><div className="two-columns"><div><h3>직원</h3>{employees.map(e=><p key={e.id}>{e.name} <span className="pill">{e.active?'재직':'사용 중지'}</span></p>)}</div><div><h3>근무지</h3>{sites.map(s=><p key={s.id}>{s.name} · {s.radius_m}m</p>)}</div></div></section></>}
      {connected&&tab==='근무 규칙'&&<><section className="panel"><h2>퇴근 기준 변경</h2><p className="muted">새 적용일부터 변경하며 이미 기록된 근태는 유지됩니다.</p><form className="form-grid" onSubmit={e=>{const data=readForm(e);const rule=rules.find(r=>r.id===field(data,'rule'));if(rule)void run(()=>client.admin.updateRule(rule.id,{...rule.values,name:rule.name,is_default:rule.is_default,effective_from:field(data,'date'),checkout_mode:'elapsed',checkout_offset_minutes:Number(field(data,'minutes'))}),'새 규칙 버전을 저장했습니다.');}}>
        <label>변경할 규칙<select name="rule" required>{rules.map(r=><option key={r.id} value={r.id}>{r.name} · {r.effective_from}</option>)}</select></label><label>적용 시작일<input name="date" type="date" defaultValue={today()} required/></label><label>인정 출근 후 경과 분<input name="minutes" type="number" defaultValue="540" min="1" max="1439" required/></label><button disabled={busy}>새 버전 저장</button></form></section>
        <section className="panel"><h2>영상팀 날짜 예외</h2><p className="muted">보고된 직원·날짜에만 13:00 출근 규칙을 적용합니다.</p><form className="form-grid" onSubmit={e=>{const data=readForm(e);void run(async()=>{const rule=await client.admin.createRule({name:'영상팀 날짜 예외',effective_from:field(data,'date'),is_default:false,check_in_start:'08:00',check_in_end:'14:00',check_out_start:'22:00',check_in_slots:['13:00'],slot_grace_minutes:10,checkout_mode:'elapsed',checkout_offset_minutes:540,missing_in_out_start:'22:00',after_slots:'pending',dedup_seconds:60});await client.admin.setException(field(data,'employee'),{rule_id:rule.id,date:field(data,'date'),reason:field(data,'reason')});},'해당 날짜에 13시 출근 예외를 등록했습니다.');}}>
        <label>직원{selectEmployee}</label><label>보고 날짜<input name="date" type="date" defaultValue={today()} required/></label><label>보고 내용<input name="reason" required/></label><button disabled={busy}>날짜 예외 등록</button></form></section>
        <section className="panel"><h2>규칙 버전</h2><div className="table-scroll"><table><thead><tr><th>이름</th><th>적용일</th><th>출근 구간</th><th>정상 퇴근</th></tr></thead><tbody>{rules.map(r=><tr key={r.id}><td>{r.name}</td><td>{r.effective_from}</td><td>{r.values.check_in_slots?.join(' · ')||r.values.work_start||'고정 규칙'}</td><td>{r.values.checkout_mode==='elapsed'?`${r.values.checkout_offset_minutes}분 후`:r.values.check_out_start}</td></tr>)}</tbody></table></div></section></>}
      {connected&&tab==='승인·이력'&&<><section className="panel"><h2>승인 대기</h2>{!pending.length&&<p className="empty">처리를 기다리는 스캔이 없습니다.</p>}{pending.map(p=><div className="pending-row" key={p.id}><div><strong>{employees.find(e=>e.id===p.employee_id)?.name}</strong><p>{time(p.scanned_at)} · {p.pending_reason}</p></div><div className="actions">{(!p.override_id?['in','out','prev_out']:['out']).map((kind)=><button className="secondary" disabled={busy} key={kind} onClick={()=>void run(()=>client.admin.approvePending(p.id,{as:kind as 'in'|'out'|'prev_out'}),'승인했습니다.')}>{({in:'당일 출근',out:'당일 퇴근',prev_out:'전날 퇴근'} as Record<string,string>)[kind]}</button>)}<button className="secondary" disabled={busy} onClick={()=>void run(()=>client.admin.dismissPending(p.id),'무시 처리했습니다.')}>무시</button></div></div>)}</section>
        <section className="panel"><h2>최근 변경 이력</h2><ul className="audit-list">{audits.slice(-20).reverse().map(a=><li key={a.id}><span>{a.target_table}</span><span>{a.actor_id}</span><time>{time(a.created_at)}</time></li>)}</ul></section></>}
      <footer className="page-footer">출퇴근 패키지 연동 예제 · Asia/Seoul</footer>
    </main></div>;
}
const mobileClient=createAttendanceClient({baseUrl:'/api/attendance'});
createRoot(document.getElementById('root')!).render(<StrictMode>{location.pathname==='/c'
  ?<MobileCheckIn client={mobileClient} companyName="테스트 장소" theme={{accent:'#184c42'}}/>
  :location.pathname==='/scanner'?<Scanner/>:<Admin/>}</StrictMode>);
