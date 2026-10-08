import type { components } from './schema.js';
export type { paths, components } from './schema.js';
type Schemas = components['schemas'];
export type RuleInput = Schemas['RuleInput'];
export type OverrideInput = Schemas['OverrideInput'];
export type AttendanceRecord = Schemas['AttendanceOutput'];
export type CheckResult = Schemas['CheckResultOutput'];
export type EmployeeQr = Schemas['EmployeeQrOutput'];
export type EmployeeStatus = Schemas['EmployeeStatusOutput'];
export type ScannerSession = Schemas['ScannerSessionOutput'];
export type ScanSummary = Schemas['ScanSummary'];
export type QrErrorCode = Schemas['QrErrorOutput']['detail'];
export type MobileConfig = Schemas['MobileConfigOutput'];
export type SiteInfo = Schemas['SiteInfoOutput'];
export interface Position { lat: number; lng: number; accuracy: number }
export interface TokenStore { get(): string | null; set(token: string): void; clear(): void }
export class AttendanceError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.name = 'AttendanceError';
  }
}
export function isDeviceAuthenticationError(error: AttendanceError): boolean {
  return (error.status === 401 && ['invalid mobile token','token expired','bearer token required'].includes(String(error.detail)))
    || (error.status === 403 && error.detail === 'device revoked');
}
export class LocationError extends Error {
  constructor(public code: 'denied' | 'unavailable' | 'timeout' | 'unsupported') {
    super(code); this.name = 'LocationError';
  }
}
export function browserTokenStore(key: string): TokenStore {
  return { get: () => localStorage.getItem(key), set: t => localStorage.setItem(key, t),
    clear: () => localStorage.removeItem(key) };
}
export function getPosition(): Promise<Position> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      reject(new LocationError('unsupported')); return;
    }
    navigator.geolocation.getCurrentPosition(p => resolve({ lat: p.coords.latitude,
      lng: p.coords.longitude, accuracy: p.coords.accuracy }), e => reject(new LocationError(
        e.code === 1 ? 'denied' : e.code === 3 ? 'timeout' : 'unavailable')),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  });
}
export function distanceM(a: Position, b: {lat: number; lng: number}): number {
  const r = Math.PI / 180;
  const x = Math.sin((b.lat-a.lat)*r/2)**2 + Math.cos(a.lat*r)*Math.cos(b.lat*r)*Math.sin((b.lng-a.lng)*r/2)**2;
  return 6371008.8 * 2 * Math.asin(Math.sqrt(Math.min(1, x)));
}
export function createAttendanceClient(options: {baseUrl: string; fetcher?: typeof fetch;
  mobileFetcher?: typeof fetch; tokenStore?: TokenStore}) {
  const base = options.baseUrl.replace(/\/$/, '');
  // Hosts with multiple tenants must also scope the token-store key per tenant.
  const tokens = options.tokenStore ?? browserTokenStore('attendance.mobile:' + base);
  async function request<T>(path: string, method = 'GET', body?: unknown, mobile = false): Promise<T> {
    const headers = new Headers({Accept:'application/json'});
    if (body !== undefined) headers.set('Content-Type', 'application/json');
    if (mobile && tokens.get()) headers.set('Authorization', 'Bearer ' + tokens.get());
    const fetcher = mobile ? options.mobileFetcher ?? fetch : options.fetcher ?? fetch;
    const response = await fetcher(base + path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)});
    if (!response.ok) {
      const data = await response.json().catch(() => ({detail: response.statusText}));
      const error = new AttendanceError(response.status, data.detail);
      if (mobile && isDeviceAuthenticationError(error)) tokens.clear();
      throw error;
    }
    return response.json() as Promise<T>;
  }
  function query(params: Record<string, string | undefined>) {
    return '?' + new URLSearchParams(Object.entries(params).filter((p): p is [string, string] => p[1] !== undefined));
  }
  return {
    employee: {
      getQr: () => request<EmployeeQr>('/me/qr'),
      getStatus: (since?: string) => request<EmployeeStatus>('/me/status' + query({since})),
    },
    admin: {
      issueEmployeeQr: (id: string) => request<EmployeeQr>('/employees/'+encodeURIComponent(id)+'/qr'),
      request: <T>(path: string, method='GET', body?: unknown) => request<T>(path, method, body),
      getAttendance: (params: {date?: string; month?: string; employee_id?: string}) => request<AttendanceRecord[]>('/attendance' + query(params)),
      getEmployees: () => request<Array<{id: string; name: string; active: boolean}>>('/employees'),
      createEmployee: (data: Schemas['EmployeeInput']) => request<{id: string; name: string; qr_token: string}>('/employees', 'POST', data),
      createRule: (data: RuleInput) => request<{id: string}>('/work-rules','POST',data),
      updateRule: (id: string, data: RuleInput) => request<{id: string}>('/work-rules/'+encodeURIComponent(id),'PATCH',data),
      setException: (id: string, data: Schemas['ExceptionInput']) => request('/employees/'+encodeURIComponent(id)+'/rule-exception','PUT',data),
      setScanOverride: (id: string, data: OverrideInput) => request('/employees/'+encodeURIComponent(id)+'/scan-override','PUT',data),
      cancelScanOverride: (id: string) => request('/employees/'+encodeURIComponent(id)+'/scan-override','DELETE'),
      approvePending: (id: string, data: Schemas['ApproveInput']) => request('/pending/'+encodeURIComponent(id)+'/approve','POST',data),
      dismissPending: (id: string) => request('/pending/'+encodeURIComponent(id)+'/dismiss','POST'),
      inviteMobile: (id: string) => request<{invite_url:string; code:string}>('/employees/'+encodeURIComponent(id)+'/mobile-invite','POST'),
    },
    mobile: {
      hasToken: () => Boolean(tokens.get()), logout: () => tokens.clear(), getPosition,
      config: () => request<MobileConfig>('/mobile/config','GET',undefined,true),
      site: (siteToken: string) => request<SiteInfo>('/mobile/site'+query({site_token:siteToken}),'GET',undefined,true),
      me: () => request<{employee_name:string; record:AttendanceRecord|null}>('/mobile/me','GET',undefined,true),
      async registerDevice(data: Schemas['RegisterInput']) {
        const result = await request<{token:string; expires_at:string}>('/mobile/register','POST',data,true);
        tokens.set(result.token); return result;
      },
      async refresh() {
        const result = await request<{token:string}>('/mobile/token/refresh','POST',undefined,true);
        tokens.set(result.token); return result;
      },
      checkIn: (data: Schemas['MobileCheckIn']) => request<CheckResult>('/mobile/checkins','POST',data,true),
      getAttendance: (month: string) => request<AttendanceRecord[]>('/mobile/attendance'+query({month}),'GET',undefined,true),
    }
  };
}
export type AttendanceClient = ReturnType<typeof createAttendanceClient>;


/** Use generated_at (not the rounded slot issued_at) as the status polling baseline. */
export function hasQrScanResult(status: EmployeeStatus): boolean {
  return status.result_since && status.latest_scan !== null
    && (['in','tardy_in','late_in','out','early_out','out_no_in','already_in','protected'].includes(status.latest_scan.result)
        || Boolean(status.latest_scan.pending_status?.startsWith('approved_')));
}
