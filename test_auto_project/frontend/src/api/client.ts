// 서버 호출 — 컴포넌트는 fetch 를 직접 쓰지 않고 여기를 거친다 (docs/react.md 8.1).
// 서버 오류는 {"error": 문구} — 문구를 그대로 ApiError.message 로. 승인 거부(refused) · 모자란 자료(missing)도 같이.
import type { components } from './schema';

export type Schemas = components['schemas'];
export type ErrorBody = Schemas['ErrorBody'];

export class ApiError extends Error {
  readonly status: number;
  readonly body: Partial<ErrorBody>;

  constructor(status: number, body: Partial<ErrorBody>) {
    super(body.error || `서버 오류 (${status})`);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }

  get refused(): boolean {
    return Boolean(this.body.refused);
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';

export interface RequestOptions {
  body?: unknown;
  signal?: AbortSignal;
  /** 진행 스트림을 받을 때 — Accept: application/x-ndjson */
  stream?: boolean;
}

/** 요청을 보내고 Response 를 그대로 돌려준다 (스트림용). 오류 응답이면 ApiError. */
export async function send(method: Method, path: string, options: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.stream) headers['Accept'] = 'application/x-ndjson';
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error;
    throw new ApiError(0, { error: '서버에 연결하지 못했습니다' });
  }
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => ({})));
  return res;
}

/** JSON 응답. T 는 schema.d.ts 의 응답 모양 (Schemas['…']). */
export async function request<T>(method: Method, path: string, options: RequestOptions = {}): Promise<T> {
  const res = await send(method, path, options);
  return (await res.json()) as T;
}

export const get = <T>(path: string, signal?: AbortSignal) => request<T>('GET', path, { signal });
export const post = <T>(path: string, body: unknown = {}) => request<T>('POST', path, { body });
export const put = <T>(path: string, body: unknown) => request<T>('PUT', path, { body });
export const del = <T>(path: string) => request<T>('DELETE', path);
