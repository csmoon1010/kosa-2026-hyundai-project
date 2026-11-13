// 가짜 API (MSW) — 테스트마다 server.use(...) 로 바꾼다. 기본은 서버 연결됨.
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

export const handlers = [
  http.get('/api/common/health', () => HttpResponse.json({ ok: true })),
  http.get('/api/admin/preprocessing/status', () =>
    HttpResponse.json({
      counts: { canonical_schema: 43, parameter_kb: 43, baseline: 43, response_outputs: 43 },
      warnings: [],
    }),
  ),
];

export const server = setupServer(...handlers);

/** NDJSON 응답 — chunks 를 그대로 나눠 보낸다 (줄이 쪼개져 와도 되는지 볼 때). */
export function ndjsonResponse(chunks: string[]) {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
  return new HttpResponse(body, { headers: { 'Content-Type': 'application/x-ndjson; charset=utf-8' } });
}
