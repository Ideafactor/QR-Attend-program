import {createSerialFramer} from "./framing.js";
import type { CheckResult, ScannerSession } from "@attendance/attendance-client";
import { type FormEvent, useEffect, useRef, useState } from "react";

const labels: Record<CheckResult["result"], string> = {
  in: "출근 완료",
  tardy_in: "지각 출근 기록",
  late_in: "늦은 출근 기록",
  out: "퇴근 완료",
  early_out: "조기 퇴근 기록",
  out_no_in: "퇴근 기록 · 출근 누락",
  pending: "관리자 승인 대기",
  duplicate: "중복 스캔",
  protected: "관리자 확정 기록 유지",
  already_in: "이미 출근 처리됨",
};

type SerialPortLike = {
  readonly readable: ReadableStream<Uint8Array> | null;
  open(options: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
};

type SerialApi = {
  requestPort(): Promise<SerialPortLike>;
};

function serialApi(): SerialApi | undefined {
  return typeof navigator === "undefined" ? undefined : (navigator as Navigator & { serial?: SerialApi }).serial;
}

export interface AttendanceScannerProps {
  baseUrl: string;
  title?: string;
  adminHref?: string;
  timeZone?: string;
}
export function AttendanceScanner({baseUrl, title="사무실 QR 스캐너", adminHref, timeZone="Asia/Seoul"}: AttendanceScannerProps) {
  const endpoint = baseUrl.replace(/\/$/, "");
  const [key, setKey] = useState("");
  const credential = useRef("");
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [focused, setFocused] = useState(false);
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  const [message, setMessage] = useState("스캐너 전용 접속 키로 연결하세요.");
  const [history, setHistory] = useState<CheckResult[]>([]);
  const [count, setCount] = useState(0);
  const [capabilities, setCapabilities] = useState<ScannerSession>();
  const [baudRate, setBaudRate] = useState(9600);
  const [serialConnected, setSerialConnected] = useState(false);
  const [serialConnecting, setSerialConnecting] = useState(false);
  const [serialBytes, setSerialBytes] = useState(0);
  const [lastSerialReceivedAt, setLastSerialReceivedAt] = useState<string>();
  const input = useRef<HTMLInputElement>(null);
  const queue = useRef<string[]>([]);
  const running = useRef(false);
  const session = useRef(0);
  const serialCycle = useRef(0);
  const serialPort = useRef<SerialPortLike | null>(null);
  const serialCleanup = useRef<Promise<void> | null>(null);
  const serialReader = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      session.current += 1;
      serialCycle.current += 1;
      credential.current = "";
      queue.current = [];
      void disconnectSerial();
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  useEffect(()=>{if(connected) input.current?.focus();},[connected]);
  function stop(reason: string): void {
    session.current += 1;
    void disconnectSerial();
    credential.current = "";
    queue.current = [];
    setCount(0);
    setConnected(false);
    setMessage(reason);
  }
  async function connect(event: FormEvent): Promise<void> {
    event.preventDefault();
    setConnecting(true);
    const current = session.current;
    try {
      const response = await fetch(`${endpoint}/session`, {
        credentials: "omit",
        headers: { Authorization: `Bearer ${key}` },
        cache: "no-store",
        signal: AbortSignal.timeout(10_000),
      });
      if(current !== session.current) return;
      if (!response.ok) {
        setMessage(
          response.status === 503
            ? "서버에 스캐너 접속 키가 설정되지 않았습니다."
            : "스캐너 접속 키를 확인하세요.",
        );
        return;
      }
      const server = (await response.json()) as ScannerSession;
      if(current !== session.current) return;
      if (!server.ready || server.transport !== "USB-COM" || server.terminator !== "CRLF"
        || server.queue_limit !== 10 || server.qr_interval_seconds !== 60
        || server.max_code_length !== 1024 || !Array.isArray(server.supported_baud_rates)
        || typeof server.baud_rate !== "number" || !server.supported_baud_rates.includes(server.baud_rate)) {
        setMessage("서버의 고정 스캐너 설정을 확인하세요.");
        return;
      }
      credential.current = key;
      setCapabilities(server);
      setBaudRate(server.baud_rate);
      setKey("");
      setConnected(true);
      setHistory([]);
      setMessage("USB-COM 포트를 연결한 뒤 직원 사무실 QR을 스캔하세요.");
    } catch {
      setMessage("서버에 연결할 수 없습니다.");
    } finally {
      setConnecting(false);
    }
  }
  async function drain(): Promise<void> {
    if (running.current) return;
    running.current = true;
    const current = session.current;
    try {
      while (queue.current.length > 0 && current === session.current) {
        const code = queue.current.shift();
        if (code === undefined) continue;
        try {
          const response = await fetch(`${endpoint}/scans`, {
            credentials: "omit",
            method: "POST",
            headers: {
              Authorization: `Bearer ${credential.current}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ code }),
            signal: AbortSignal.timeout(15_000),
          });
          if (current !== session.current) return;
          if (response.status === 401) {
            stop("스캐너 연결이 해제되었습니다. 대기 중인 QR은 전송하지 않았습니다.");
            return;
          }
          if (response.status >= 500) throw new Error("UNCERTAIN_SCAN_RESULT");
          if (!response.ok) {
            const error=await response.json().catch(()=>({detail:""}));
            const detail=error.detail ?? error.error?.code;
            setMessage(
              response.status === 410
                ? "만료된 QR입니다. 직원 화면의 새 QR을 스캔하세요."
                : response.status === 409 && detail === "ATTENDANCE_QR_ALREADY_USED"
                  ? "이미 사용한 QR입니다. 새 QR이 표시된 뒤 다시 스캔하세요."
                  : response.status === 404
                    ? "등록되지 않은 직원 QR입니다."
                    : response.status === 403
                      ? "사용이 중지된 직원 QR입니다."
                      : response.status === 409 ? "기록을 처리할 수 없습니다. 관리자에게 근무 규칙과 확정 기록을 확인해 주세요."
                      : "직원 출퇴근 QR 형식을 확인하세요.",
            );
          } else {
            const result = (await response.json()) as CheckResult;
            if (!result || !Object.hasOwn(labels, result.result) || typeof result.scan_id !== "string"
                || typeof result.employee_name !== "string" || !Number.isFinite(Date.parse(result.recorded_at))) {
              throw new Error("UNCERTAIN_SCAN_RESULT");
            }
            setHistory((old) => [result, ...old].slice(0, 10));
            setMessage(`${result.employee_name} · ${labels[result.result]}`);
          }
          setCount(queue.current.length);
        } catch {
          if (current === session.current)
            stop(
              "처리 여부 확인 필요: 관리자 기록에서 마지막 스캔을 확인하세요. 자동 재전송하지 않았습니다.",
            );
          return;
        }
      }
    } finally {
      running.current = false;
    }
  }
  function enqueueCode(rawCode: string): void {
    const code = rawCode.trim();
    if (!code || !credential.current) return;
    if (!navigator.onLine) {
      setMessage("오프라인입니다. 연결 복구 후 다시 스캔하세요.");
      return;
    }
    if (!/^[A-Za-z0-9._-]{1,1024}$/.test(code)) {
      setMessage("직원 사무실 QR인지, 키보드가 영문 입력인지 확인하세요.");
      return;
    }
    if (queue.current.length >= (capabilities?.queue_limit ?? 10)) {
      setMessage("대기열이 가득 찼습니다. 방금 QR은 처리 후 다시 스캔하세요.");
      return;
    }
    queue.current.push(code);
    setCount(queue.current.length + (running.current ? 1 : 0));
    void drain();
  }
  function scan(event: FormEvent): void {
    event.preventDefault();
    const code = input.current?.value ?? "";
    if (input.current !== null) input.current.value = "";
    enqueueCode(code);
  }
  async function disconnectSerial(): Promise<void> {
    serialCycle.current += 1;
    const reader = serialReader.current;
    try { await reader?.cancel(); } catch { /* unplugged */ }
    await serialCleanup.current;
    setSerialConnected(false);
  }
  async function readSerial(port: SerialPortLike, cycle: number): Promise<void> {
    const reader = port.readable?.getReader();
    if (reader === undefined) {
      setMessage("선택한 포트에서 QR 데이터를 읽을 수 없습니다.");
      try {await port.close();} catch { /* already closed */ }
      if(serialPort.current === port) serialPort.current=null;
      setSerialConnected(false);
      return;
    }
    serialReader.current = reader;
    const decoder = new TextDecoder();
    const framer = createSerialFramer();
    let idleFlush: number | undefined;
    const flushBuffer = () => {
      const code = framer.flush();
      if (code && cycle === serialCycle.current) enqueueCode(code);
    };
    try {
      while (cycle === serialCycle.current) {
        const { value, done } = await reader.read();
        if (done || cycle !== serialCycle.current) break;
        setSerialBytes((current) => current + value.byteLength);
        setLastSerialReceivedAt(new Date().toLocaleTimeString("ko-KR", { timeZone }));
        const frames = framer.push(decoder.decode(value, {stream:true}));
        for(const code of frames.codes) enqueueCode(code);
        if (idleFlush !== undefined) window.clearTimeout(idleFlush);
        idleFlush = window.setTimeout(flushBuffer, 150);
        if(frames.overflowed) setMessage("QR 데이터가 너무 깁니다. 종료 문자 설정을 확인하세요.");
      }
    } catch {
      if (cycle === serialCycle.current)
        setMessage("USB-COM 연결이 끊겼습니다. 포트를 다시 연결하세요.");
    } finally {
      if (idleFlush !== undefined) window.clearTimeout(idleFlush);
      try {
        reader.releaseLock();
      } catch {
        // The reader may already have released its lock after device removal.
      }
      if (serialReader.current === reader) serialReader.current = null;
      try { await port.close(); } catch { /* unplugged */ }
      if (serialPort.current === port) {
        serialPort.current = null;
        setSerialConnected(false);
      }
    }
  }
  async function connectSerial(): Promise<void> {
    const api = serialApi();
    if (api === undefined) {
      setMessage("USB-COM은 데스크톱 Chrome 또는 Edge의 HTTPS 화면에서 연결할 수 있습니다.");
      return;
    }
    setSerialConnecting(true);
    const cycle = ++serialCycle.current;
    const current = session.current;
    try {
      const port = await api.requestPort();
      if(cycle !== serialCycle.current || current !== session.current || !credential.current) return;
      await port.open({ baudRate });
      if(cycle !== serialCycle.current || current !== session.current || !credential.current) {
        await port.close(); return;
      }
      serialPort.current = port;
      setSerialBytes(0);
      setLastSerialReceivedAt(undefined);
      setSerialConnected(true);
      setMessage("USB-COM 연결됨 · 직원 사무실 QR을 스캔하세요.");
      serialCleanup.current = readSerial(port, cycle);
    } catch (error) {
      setMessage(
        error instanceof DOMException && error.name === "NotFoundError"
          ? "USB-COM 포트 선택을 취소했습니다."
          : "USB-COM 포트를 열지 못했습니다. 장치와 통신 속도를 확인하세요.",
      );
    } finally {
      setSerialConnecting(false);
    }
  }

  return (
    <main className="scanner-page">
      {adminHref&&<a href={adminHref}>관리자 화면</a>}
      <h1>{title}</h1>
      <p>USB-COM 직접 수신 · USB-KBW 비상 입력</p>
      <p className="scanner-message" role="status" aria-live="polite">
        {message}
      </p>
      {online ? null : <p role="alert">네트워크 연결이 끊겼습니다.</p>}
      {connected ? (
        <>
          <section className="scanner-readiness" aria-label="스캐너 준비 상태">
            <h2>운영 준비 상태</h2>
            <ul>
              <li data-ready="true">서버 인증 연결됨</li>
              <li data-ready={online}>{online ? "네트워크 연결됨" : "네트워크 연결 끊김"}</li>
              <li data-ready={serialApi() !== undefined}>
                {serialApi() === undefined
                  ? "Web Serial 미지원 · 데스크톱 Chrome/Edge 필요"
                  : "Web Serial 사용 가능"}
              </li>
              <li data-ready={serialConnected}>
                {serialConnected ? "USB-COM 포트 연결됨" : "USB-COM 포트 연결 필요"}
              </li>
              <li data-ready={serialBytes > 0}>
                {serialBytes > 0
                  ? `장치 데이터 ${serialBytes} byte 수신 · ${lastSerialReceivedAt}`
                  : "장치 데이터 대기 중"}
              </li>
              <li data-ready="true">
                {capabilities?.transport ?? "USB-COM"} · {baudRate} baud · 종료 문자{" "}
                {capabilities?.terminator ?? "CRLF"} · QR {capabilities?.qr_interval_seconds ?? 60}
                초
              </li>
            </ul>
          </section>
          <section className="scanner-serial" aria-label="USB-COM 연결">
            <label>
              통신 속도
              <select
                value={baudRate}
                disabled={serialConnected || serialConnecting}
                onChange={(event) => setBaudRate(Number(event.target.value))}
              >
                {(capabilities?.supported_baud_rates ?? [9600]).map((value) => (
                  <option key={value} value={value}>
                    {value} baud
                  </option>
                ))}
              </select>
            </label>
            {serialConnected ? (
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  void disconnectSerial().then(() => setMessage("USB-COM 연결을 해제했습니다."));
                }}
              >
                USB-COM 연결 해제
              </button>
            ) : (
              <button
                type="button"
                disabled={serialConnecting}
                onClick={() => void connectSerial()}
              >
                {serialConnecting ? "포트 연결 중…" : "USB-COM 포트 연결"}
              </button>
            )}
          </section>
          <form className="scanner-fallback" onSubmit={scan}>
            <label>
              QR 스캔 입력
              <input
                ref={input}
                type="password"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.repeat || event.nativeEvent.isComposing))
                    event.preventDefault();
                }}
              />
            </label>
            <p>
              {focused ? "USB-KBW 입력 대기 중" : "비상 입력을 사용할 때만 활성화하세요."} · 처리
              대기 {count}건
            </p>
            <button type="button" onClick={() => input.current?.focus()}>
              입력창 활성화
            </button>
          </form>
          <button
            type="button"
            className="secondary"
            disabled={count > 0}
            onClick={() => {
              stop("연결을 해제했습니다.");
              setHistory([]);
            }}
          >
            연결 해제
          </button>
        </>
      ) : (
        <form onSubmit={(event) => void connect(event)}>
          <label>
            스캐너 접속 키
            <input
              type="password"
              autoComplete="off"
              required
              value={key}
              onChange={(event) => setKey(event.target.value)}
            />
          </label>
          <button type="submit" disabled={connecting || running.current}>
            {connecting ? "연결 중…" : "스캐너 연결"}
          </button>
        </form>
      )}
      <section aria-label="최근 스캔">
        <h2>최근 스캔</h2>
        {history.map((result) => (
          <article key={`${result.recorded_at}-${result.employee_name}-${result.result}`}>
            <strong>
              {result.employee_name} · {labels[result.result]}
            </strong>
            <time>
              {new Date(result.recorded_at).toLocaleTimeString("ko-KR", { timeZone })}
            </time>
            {result.pending_reason == null ? null : (
              <p>관리자에게 승인 대기 내역을 확인해 주세요.</p>
            )}
          </article>
        ))}
      </section>
      <p>
        화면을 새로 열면 다시 연결해야 합니다. 접속 키와 QR 원문은 브라우저 저장소에 저장하지
        않습니다.
      </p>
    </main>
  );
}
