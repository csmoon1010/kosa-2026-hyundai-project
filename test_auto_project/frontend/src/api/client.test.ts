import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { server } from '../test/server';
import { ApiError, get, post } from './client';

describe('client', () => {
  it('JSON 응답을 돌려준다', async () => {
    expect(await get('/api/common/health')).toEqual({ ok: true });
  });

  it('서버의 {"error"} 문구를 그대로 오류로 — 승인 거부(refused) 포함', async () => {
    server.use(
      http.post('/api/inspect/approve', () =>
        HttpResponse.json({ error: '시나리오 승인이 필요합니다', refused: true }, { status: 400 }),
      ),
    );
    const error = await post('/api/inspect/approve', {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe('시나리오 승인이 필요합니다');
    expect((error as ApiError).status).toBe(400);
    expect((error as ApiError).refused).toBe(true);
  });

  it('본문 없는 오류는 상태 코드로', async () => {
    server.use(http.get('/api/x', () => new HttpResponse('boom', { status: 502 })));
    await expect(get('/api/x')).rejects.toThrow('서버 오류 (502)');
  });

  it('보낸 본문은 JSON', async () => {
    let seen: unknown;
    server.use(
      http.post('/api/run/dry-run', async ({ request }) => {
        seen = { type: request.headers.get('Content-Type'), body: await request.json() };
        return HttpResponse.json({ run: {} });
      }),
    );
    await post('/api/run/dry-run', { items: [{ id: 'a', n: 1 }] });
    expect(seen).toEqual({ type: 'application/json', body: { items: [{ id: 'a', n: 1 }] } });
  });
});
