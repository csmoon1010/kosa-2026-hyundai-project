// 테스트 견본 — 저장소의 실제 화면 데이터 (2026-11-13). 전처리 산출물은 물류 API 2개 · 필드 몇 개만, 필드 목록은 물류만 남겼다.
import { http, HttpResponse } from 'msw';

import data from './admin.json';

const clone = <T>(x: T): T => structuredClone(x);
export const admin = () => clone(data);

/** 관리자 화면 데이터 API 흉내 — 각 조각을 그대로 */
export function adminHandlers(d = admin()) {
  const parts: Record<string, unknown> = { ...d };
  return [
    http.get('/api/admin/:part', ({ params }) => {
      const body = parts[String(params.part)];
      return body ? HttpResponse.json(body) : HttpResponse.json({ error: '없는 경로' }, { status: 404 });
    }),
    http.get('/api/admin/preprocessing/status', () =>
      HttpResponse.json({ counts: d.preprocessing.preprocessing.counts, warnings: [] }),
    ),
  ];
}
