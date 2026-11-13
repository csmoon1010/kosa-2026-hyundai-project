// 진행 스트림(NDJSON) — 서버가 한 줄씩 보내는 진행 이벤트를 받는다 (docs/react.md 8.1, 서버는 tap/api/streaming.py).
//
// - 작업 상태는 화면(컴포넌트) 밖에 이름(key)별로 둔다 → 다른 메뉴로 갔다 와도 진행이 이어진다 (예전 화면과 같다).
// - 연결이 끊기면 받은 데까지의 줄은 그대로 두고 status 'error'.
// - 진행 중에는 새로고침 · 창 닫기를 경고한다.
import { useCallback, useEffect, useSyncExternalStore } from 'react';

import { send } from './client';

/** 응답을 한 줄씩 onEvent 로. 진행 줄이 없는 응답(application/json)이면 그 JSON 을 돌려준다. */
export async function readNdjson<E>(res: Response, onEvent: (event: E) => void): Promise<unknown> {
  if (!(res.headers.get('Content-Type') ?? '').includes('ndjson')) return res.json();
  const onLine = (line: string) => {
    if (line.trim()) onEvent(JSON.parse(line) as E);
  };
  if (!res.body) {
    (await res.text()).split('\n').forEach(onLine);
    return null;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    lines.forEach(onLine);
  }
  onLine(buffer + decoder.decode());
  return null;
}

/** POST 로 진행 스트림을 받는다 — 줄마다 onEvent, 진행 줄 없는 JSON 응답이면 그 JSON 을 돌려준다. 오류 응답이면 ApiError. */
export async function postStream<E>(
  path: string,
  body: unknown,
  onEvent: (event: E) => void,
): Promise<unknown> {
  const res = await send('POST', path, { body, stream: true });
  return readNdjson(res, onEvent);
}

export type StreamStatus = 'idle' | 'running' | 'done' | 'error';

export interface StreamState<E> {
  status: StreamStatus;
  /** 받은 줄 전부 (순서대로) */
  events: E[];
  /** 마지막으로 받은 줄 */
  last: E | null;
  /** 진행 줄 없이 JSON 하나로 온 응답 */
  json: unknown;
  error: Error | null;
}

const IDLE: StreamState<never> = { status: 'idle', events: [], last: null, json: null, error: null };

interface Job {
  state: StreamState<unknown>;
  listeners: Set<() => void>;
}

const jobs = new Map<string, Job>();

function jobOf(key: string): Job {
  let job = jobs.get(key);
  if (!job) {
    job = { state: IDLE, listeners: new Set() };
    jobs.set(key, job);
  }
  return job;
}

function update(key: string, change: (state: StreamState<unknown>) => StreamState<unknown>) {
  const job = jobOf(key);
  job.state = change(job.state);
  job.listeners.forEach((listener) => listener());
}

/** key 이름의 작업을 시작한다. 같은 이름의 작업이 진행 중이면 아무것도 하지 않는다. */
export async function startStream(key: string, path: string, body: unknown): Promise<void> {
  if (jobOf(key).state.status === 'running') return;
  update(key, () => ({ ...IDLE, status: 'running' }));
  try {
    const json = await postStream(path, body, (event) =>
      update(key, (s) => ({ ...s, events: [...s.events, event], last: event })),
    );
    update(key, (s) => ({ ...s, status: 'done', json }));
  } catch (error) {
    update(key, (s) => ({ ...s, status: 'error', error: error as Error }));
  }
}

export function resetStream(key: string) {
  if (jobOf(key).state.status !== 'running') update(key, () => IDLE);
}

/** 테스트용 — 모든 작업 상태를 지운다. */
export function clearStreams() {
  jobs.clear();
}

/** 진행 스트림 상태와 시작 · 초기화 함수. E 는 줄 모양 (schema.d.ts 의 …Event). */
export function useNdjson<E>(key: string) {
  const subscribe = useCallback(
    (listener: () => void) => {
      const job = jobOf(key);
      job.listeners.add(listener);
      return () => job.listeners.delete(listener);
    },
    [key],
  );
  const snapshot = useCallback(() => jobOf(key).state as StreamState<E>, [key]);
  const state = useSyncExternalStore(subscribe, snapshot, snapshot);

  useEffect(() => {
    if (state.status !== 'running') return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [state.status]);

  const start = useCallback((path: string, body: unknown) => startStream(key, path, body), [key]);
  const reset = useCallback(() => resetStream(key), [key]);
  return { ...state, start, reset };
}
