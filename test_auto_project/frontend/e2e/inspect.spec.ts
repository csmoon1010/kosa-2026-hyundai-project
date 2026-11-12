import { expect, test } from '@playwright/test';

// 화면 점검 3 (docs/fastapi.md 6.3) 을 가짜 LLM 서버로 — 분석 → 승인 → 혜정 IR 영역 자동 생성(로그 · STEP) → 다시 생성 · 로그 내려받기
test('확인용 — 분석 · 승인 · IR 생성', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(e.message));

  await page.goto('/inspect');
  await page.getByLabel('자연어 요청').fill('배송완료된 주문 1건을 배송완료 취소시켜줘');
  await page.getByRole('button', { name: '분석 (의도 → 경로 → API)' }).click();
  await expect(page.getByRole('heading', { name: '3단계 에이전트 결과' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '③ API 선택' })).toBeVisible();

  await page.getByLabel('승인자').fill('테스트');
  await page.getByRole('button', { name: '승인 (승인본 고정)' }).click();
  await expect(page.getByText('승인본을 고정했어요.')).toBeVisible();
  await expect(page.getByText('IR 초안 저장 완료 · 실행용 시나리오에는 등록하지 않았습니다.')).toBeVisible();
  const steps = page.getByRole('navigation', { name: '시나리오 단계 선택' }).getByRole('button');
  await expect(steps).toHaveCount(2);
  await steps.nth(1).click();
  await expect(page.getByRole('heading', { name: /^STEP 1-2 · / })).toBeVisible();

  // 로그 내려받기 링크가 실제 JSONL 을 준다
  const href = await page.getByRole('link', { name: 'JSONL 다운로드' }).getAttribute('href');
  const res = await page.request.get(href!);
  expect(res.ok()).toBe(true);
  expect((await res.text()).split('\n')[0]).toContain('generation_start');

  // 승인본을 골라 다시 생성
  await page.getByRole('button', { name: 'IR 다시 생성' }).click();
  await expect(page.getByText('IR 초안 저장 완료 · 실행용 시나리오에는 등록하지 않았습니다.')).toBeVisible();
  await expect(page.getByText(/^JSONL 로그 2 \/ 2개/)).toBeVisible();

  expect(errors).toEqual([]);
});
