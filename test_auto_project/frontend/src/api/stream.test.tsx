import { act, renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { ndjsonResponse, server } from '../test/server';
import { readNdjson, useNdjson } from './stream';

const collect = async (res: Response) => {
  const events: unknown[] = [];
  const json = await readNdjson(res, (e) => events.push(e));
  return { events, json };
};

describe('readNdjson', () => {
  it('줄이 나뉘어 와도 한 줄씩, 마지막 줄 줄바꿈이 없어도 읽는다', async () => {
    const res = ndjsonResponse([
      '{"event":"st',
      'age","stage":"intent"}\n{"event":"stage",',
      '"stage":"paths"}\n{"event":"done"}',
    ]);
    expect(await collect(res)).toEqual({
      events: [{ event: 'stage', stage: 'intent' }, { event: 'stage', stage: 'paths' }, { event: 'done' }],
      json: null,
    });
  });

  it('한글이 바이트 경계에서 잘려도 깨지지 않는다', async () => {
    const bytes = new TextEncoder().encode('{"stage":"요청 이해"}\n');
    const body = new ReadableStream({
      start(c) {
        c.enqueue(bytes.slice(0, 13));
        c.enqueue(bytes.slice(13));
        c.close();
      },
    });
    const res = new Response(body, { headers: { 'Content-Type': 'application/x-ndjson' } });
    expect((await collect(res)).events).toEqual([{ stage: '요청 이해' }]);
  });

  it('진행 줄이 없는 JSON 응답이면 그 JSON 을 돌려준다', async () => {
    const res = Response.json({ request: 'q' });
    expect(await collect(res)).toEqual({ events: [], json: { request: 'q' } });
  });
});

describe('useNdjson', () => {
  it('줄마다 상태를 바꾸고 끝나면 done — 같은 이름이면 다른 화면에서도 같은 상태', async () => {
    let sent: unknown;
    server.use(
      http.post('/api/register/analyze', async ({ request }) => {
        sent = { accept: request.headers.get('Accept'), body: await request.json() };
        return ndjsonResponse(['{"event":"stage","stage":"intent"}\n', '{"event":"done","result":{}}\n']);
      }),
    );
    const { result } = renderHook(() => useNdjson<{ event: string }>('analyze'));
    expect(result.current.status).toBe('idle');
    act(() => void result.current.start('/api/register/analyze', { utterance: 'q' }));
    await waitFor(() => expect(result.current.status).toBe('done'));
    expect(result.current.events.map((e) => e.event)).toEqual(['stage', 'done']);
    expect(result.current.last?.event).toBe('done');
    expect(sent).toEqual({ accept: 'application/x-ndjson', body: { utterance: 'q' } });

    const other = renderHook(() => useNdjson<{ event: string }>('analyze')); // 메뉴를 옮겨 다시 그려도
    expect(other.result.current.events).toHaveLength(2);
    act(() => other.result.current.reset());
    expect(result.current.status).toBe('idle');
  });

  it('요청이 거부되면 error — 서버 문구 그대로', async () => {
    server.use(
      http.post('/api/register/ir', () => HttpResponse.json({ error: '서버가 모릅니다' }, { status: 400 })),
    );
    const { result } = renderHook(() => useNdjson('ir'));
    act(() => void result.current.start('/api/register/ir', {}));
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error?.message).toBe('서버가 모릅니다');
  });

  it('진행 중에는 새로고침을 경고한다', async () => {
    let finish!: () => void;
    server.use(
      http.post('/api/register/analyze', async () => {
        await new Promise<void>((resolve) => (finish = resolve));
        return ndjsonResponse(['{"event":"done"}\n']);
      }),
    );
    const { result } = renderHook(() => useNdjson('slow'));
    act(() => void result.current.start('/api/register/analyze', {}));
    await waitFor(() => expect(result.current.status).toBe('running'));
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    finish();
    await waitFor(() => expect(result.current.status).toBe('done'));
    const after = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });
});
