import { useCallback, useEffect, useRef, useState, type ComponentType, type CSSProperties } from 'react';
import { AttendanceError, isDeviceAuthenticationError, LocationError, distanceM, type AttendanceClient, type AttendanceRecord,
  type CheckResult, type MobileConfig, type Position, type SiteInfo } from '@attendance/attendance-client';

export type CheckState = 'needs_registration'|'locating'|'location_denied'|'ready'|'submitting'|'result'|'error'|'registered';
export function useCheckIn({client, siteToken}: {client: AttendanceClient; siteToken?: string}) {
  const [state,setState] = useState<CheckState>('locating');
  const [position,setPosition] = useState<Position>();
  const [site,setSite] = useState<SiteInfo>();
  const [config,setConfig] = useState<MobileConfig>();
  const [result,setResult] = useState<CheckResult>();
  const [error,setError] = useState<Error>();
  const requestId = useRef(0);
  const submitting = useRef(false);
  const fail = useCallback((e: unknown) => {
    const error = e instanceof Error ? e : new Error(String(e));
    setError(error);
    setState(error instanceof LocationError && error.code === 'denied' ? 'location_denied' :
      error instanceof AttendanceError && isDeviceAuthenticationError(error) ? 'needs_registration' : 'error');
  }, []);
  const retry = useCallback(async () => {
    const id = ++requestId.current;
    setError(undefined); setResult(undefined); setState('locating');
    try {
      const settings = await client.mobile.config();
      if (id !== requestId.current) return;
      setConfig(settings);
      if (!client.mobile.hasToken()) {setState('needs_registration'); return;}
      if (!siteToken) {await client.mobile.me(); if (id === requestId.current) setState('registered'); return;}
      const [site, position] = await Promise.all([client.mobile.site(siteToken), client.mobile.getPosition()]);
      if (id !== requestId.current) return;
      setSite(site); setPosition(position); setState('ready');
    } catch(e) {if (id === requestId.current) fail(e);}
  }, [client, siteToken, fail]);
  useEffect(() => {void retry(); return () => {requestId.current++;};}, [retry]);
  const submit = useCallback(async () => {
    if (!siteToken || !position || state !== 'ready' || submitting.current) return;
    submitting.current = true; setState('submitting');
    try {
      // Refresh GPS at submission, so a stale preview is never submitted as a fresh fix.
      const fresh = await client.mobile.getPosition();
      const response = await client.mobile.checkIn({site_token:siteToken,...fresh});
      setPosition(fresh); setResult(response); setState('result');
    } catch(e) {fail(e);} finally {submitting.current = false;}
  }, [client, siteToken, position, state, fail]);
  const register = useCallback(async (code: string) => {
    if (!config || submitting.current) return;
    submitting.current = true; setState('submitting');
    try {
      await client.mobile.registerDevice({code, consent:true, consent_version:config.consent_version});
      await retry();
    } catch(e) {fail(e);} finally {submitting.current = false;}
  }, [client, config, retry, fail]);
  useEffect(() => {if (state === 'ready' && config?.confirm_before_checkin === false) void submit();}, [state,config,submit]);
  return {state, position, site, config, result, error, submit, retry, register,
    distanceM: position && site ? distanceM(position,site) : undefined};
}
export type CheckController = ReturnType<typeof useCheckIn>;
type SlotProps = {check: CheckController};
const defaults: Record<string,string> = {
  title:'출퇴근 체크', loading:'확인하고 있습니다…', register:'휴대폰 등록', consent:'위치정보 수집·이용에 동의합니다.',
  invite:'관리자에게 휴대폰 등록 초대 링크를 요청하세요.', registered:'등록되었습니다. 근무지 QR을 스캔해 주세요.',
  submit:'기록하기', retry:'다시 시도', history:'내 기록', install:'자주 사용한다면 브라우저 메뉴에서 홈 화면에 추가하세요.',
  denied:'위치 권한을 켜 주세요.', iphone:'iPhone: 설정 → 개인정보 보호 및 보안 → 위치 서비스에서 사용 중인 브라우저의 위치 권한을 확인하세요.',
  android:'Android: 설정 → 앱 → 사용 중인 브라우저 → 권한에서 위치를 허용하고 사이트의 위치 권한도 확인하세요.',
  'result.in.title':'출근 완료', 'result.tardy_in.title':'지각 출근 기록', 'result.late_in.title':'늦은 출근 기록',
  'result.out.title':'퇴근 완료', 'result.early_out.title':'조기 퇴근 기록', 'result.out_no_in.title':'퇴근 기록 · 출근 누락',
  'result.pending.title':'관리자 승인 대기', 'result.duplicate.title':'이미 기록된 스캔입니다.',
  'result.protected.title':'관리자가 확정한 기록이 유지됩니다.', 'result.already_in.title':'이미 출근했습니다.',
  distance:'근무지까지', accuracy:'위치 정확도', radius:'허용 반경', preview:'예상 판정', unknown:'기록 결과',
  actual:'실제 출근', credited:'인정 출근', checkout:'퇴근', expected:'정상 퇴근 기준',
  outside_geofence:'근무지 반경 밖입니다.', low_accuracy:'위치 정확도가 낮습니다.', early_hours:'출근 인정 시작 전입니다.',
  outside_schedule:'출근 시간 범위 밖입니다.', retention:'GPS · {months}개월',
  'error.denied':'브라우저의 위치 권한을 허용한 후 다시 시도하세요.',
  'error.unavailable':'현재 위치를 확인할 수 없습니다. 위치 서비스를 확인하세요.',
  'error.timeout':'위치 확인 시간이 초과됐습니다. 다시 시도하세요.',
  'error.unsupported':'위치 확인을 지원하는 브라우저에서 HTTPS 주소로 접속하세요.',
  'error.401':'QR 또는 초대 링크가 유효하지 않습니다. 관리자에게 새 링크를 요청하세요.',
  'error.403':'사용 권한을 확인할 수 없습니다. 관리자에게 문의하세요.',
  'error.404':'QR 정보를 찾을 수 없습니다. 최신 QR을 확인하세요.',
  'error.409':'등록 또는 기록 상태가 변경됐습니다. 새로 확인하거나 관리자에게 문의하세요.',
  'error.410':'QR이 만료됐습니다. 현장의 최신 QR을 다시 스캔하세요.',
  'error.422':'입력 정보를 확인한 후 다시 시도하세요.',
  'error.default':'처리하지 못했습니다. 연결 상태를 확인하고 다시 시도하세요.',
};
export interface MobileCheckInProps {
  client: AttendanceClient; companyName?: string; siteToken?: string; inviteCode?: string; logoUrl?: string;
  theme?: {accent?: string; radius?: number; fontFamily?: string}; messages?: Record<string,string>;
  slots?: {Header?: ComponentType<SlotProps>; Consent?: ComponentType<SlotProps & {inviteCode?:string}>;
    Result?: ComponentType<SlotProps>};
}
export function MobileCheckIn(props: MobileCheckInProps) {
  const params = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : new URLSearchParams();
  const siteToken = props.siteToken ?? params.get('t') ?? undefined;
  const inviteCode = props.inviteCode ?? params.get('invite') ?? undefined;
  const c = useCheckIn({client:props.client,siteToken});
  const [consent,setConsent] = useState(false);
  const [records,setRecords] = useState<AttendanceRecord[]>();
  const [historyError,setHistoryError] = useState<string>();
  const [month,setMonth] = useState(() => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Seoul',year:'numeric',month:'2-digit'}).format(new Date()).slice(0,7));
  const messages = {...defaults,...props.messages};
  const text = (key:string) => messages[key] ?? key;
  const style = {maxWidth:480,margin:'24px auto',padding:24,lineHeight:1.6,
    fontFamily:props.theme?.fontFamily ?? 'system-ui, sans-serif',color:'#182230',background:'#fff',
    border:'1px solid #d0d5dd',borderRadius:props.theme?.radius ?? 12,
    '--att-accent':props.theme?.accent ?? '#0b5cad'} as CSSProperties;
  const button = {padding:'12px 18px',background:'var(--att-accent)',color:'#fff',border:0,
    borderRadius:8,fontSize:16,cursor:'pointer'} as CSSProperties;
  const Header = props.slots?.Header, Consent = props.slots?.Consent, Result = props.slots?.Result;
  const format = (value?:string|null) => value ? new Date(value).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul'}) : '—';
  return <main style={style}>
    {Header ? <Header check={c}/> : <header>{props.logoUrl && <img src={props.logoUrl} alt={props.companyName ?? ''} width={100}/>}
      <p>{props.companyName}</p><h1>{text('title')}</h1></header>}
    <section aria-live="polite" aria-busy={c.state === 'submitting' || c.state === 'locating'}>
      {(c.state === 'locating' || c.state === 'submitting') && <p>{text('loading')}</p>}
      {c.state === 'needs_registration' && (Consent ? <Consent check={c} inviteCode={inviteCode}/> : <>
        <h2>{text('register')}</h2>{inviteCode ? <><p>{c.config?.consent_text}</p>
          <p>{text('retention').replace('{months}',String(c.config?.location_months ?? ''))}</p><label><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>{text('consent')}</label>
          <p><button style={button} disabled={!consent} onClick={()=>void c.register(inviteCode)}>{text('register')}</button></p></> : <p>{text('invite')}</p>}</>)}
      {c.state === 'registered' && <p>{text('registered')}</p>}
      {c.state === 'ready' && <><h2>{c.site?.name}</h2><p>{format(c.site?.server_time)}</p>
        <p>{text('distance')}: {Math.round(c.distanceM ?? 0)}m · {text('radius')}: {c.site?.radius_m}m</p>
        <p>{text('accuracy')}: ±{Math.round(c.position?.accuracy ?? 0)}m</p><p>{text('preview')}: {text('result.'+c.site?.preview+'.title')}</p>
        <button style={button} onClick={()=>void c.submit()}>{text('submit')}</button></>}
      {c.state === 'result' && (Result ? <Result check={c}/> : <><h2>{text('result.'+c.result?.result+'.title')}</h2>
        <p>{format(c.result?.recorded_at)}</p>{c.result?.pending_reason && <p>{text(c.result.pending_reason)}</p>}
        {c.result?.distance_m != null && <p>{text('distance')}: {Math.round(c.result.distance_m)}m · {text('radius')}: {c.result.radius_m}m</p>}
        {c.result?.record && <dl>{(['in_at','credited_in_at','expected_out_at','out_at'] as const).map((k,i)=><div key={k}>
          <dt>{text(['actual','credited','expected','checkout'][i])}</dt><dd>{format(c.result?.record?.[k])}</dd></div>)}</dl>}
        {c.result?.result === 'pending' && c.config?.show_retry_outside && <button style={button} onClick={()=>void c.retry()}>{text('retry')}</button>}</>)}
      {c.state === 'location_denied' && <><h2>{text('denied')}</h2><p>{text('iphone')}</p><p>{text('android')}</p></>}
      {(c.state === 'error' || c.state === 'location_denied') && <><p role="alert">{text(c.error instanceof LocationError ? 'error.'+c.error.code : c.error instanceof AttendanceError && messages['error.'+c.error.status] ? 'error.'+c.error.status : 'error.default')}</p>
        <button style={button} onClick={()=>void c.retry()}>{text('retry')}</button></>}
    </section>
    {c.config?.allow_my_records && props.client.mobile.hasToken() && <section><h2>{text('history')}</h2>
      <input aria-label={text('history')} type="month" value={month} onChange={e=>setMonth(e.target.value)}/>
      <button onClick={()=>{setHistoryError(undefined); void props.client.mobile.getAttendance(month).then(setRecords).catch(e=>setHistoryError(String(e)));}}>{text('history')}</button>
      {historyError && <p role="alert">{historyError}</p>}<ul>{records?.map(r=><li key={r.id}>{r.work_date} · {format(r.credited_in_at)} → {format(r.out_at)} {r.label}</li>)}</ul></section>}
    <footer><p>{text('install')}</p></footer>
  </main>;
}
