import { expect, test } from '@playwright/test';

// 화면 점검 1 (docs/fastapi.md 6.3) 을 가짜 LLM 서버로 — 이름 · 요청 → 분석 → IR → 승인 · 등록 → 목록 → 열기 · 삭제
test('시나리오 등록 — 분석부터 삭제까지', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(e.message));

  await page.goto('/register');
  await expect(page.getByText(/등록된 시나리오가 없습니다/)).toBeVisible();

  await page.getByLabel('시나리오 이름').fill('E2E 배송완료 취소');
  await page.getByLabel('자연어 요청').fill('배송완료된 주문 1건을 배송완료 취소시켜줘');
  await page.getByLabel('자연어 요청').press('Control+Enter');

  const steps = page.getByRole('list', { name: '진행 단계' }).getByRole('listitem');
  await expect(steps).toHaveCount(4);
  await expect(page.getByRole('heading', { name: '시나리오 미리보기' })).toBeVisible();
  await expect(steps.last()).toHaveAttribute('data-s', 'done');
  await expect(page.getByText('배송완료 데이터 찾기')).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '필드설명' }).first()).toBeVisible();

  await page.getByLabel('승인자').fill('테스트');
  await page.getByRole('button', { name: '승인하고 등록' }).click();
  await expect(page.getByText('✓ 등록했어요 — E2E 배송완료 취소')).toBeVisible();

  const row = page.getByRole('row', { name: 'E2E 배송완료 취소 보기' });
  await expect(row).toBeVisible();
  await row.click();
  await expect(page.getByRole('heading', { name: 'E2E 배송완료 취소' })).toBeVisible();
  await expect(page.getByText(/✓ 등록됨 — 승인 테스트/)).toBeVisible();
  await page.getByRole('button', { name: '닫기' }).click();

  await row.getByRole('button', { name: '삭제' }).click();
  await row.getByRole('button', { name: '삭제 확인' }).click();
  await expect(page.getByText(/등록된 시나리오가 없습니다/)).toBeVisible();

  expect(errors).toEqual([]);
});

test('분석 중 다른 메뉴로 갔다 와도 결과가 남는다', async ({ page }) => {
  await page.goto('/register');
  await page.getByLabel('자연어 요청').fill('배송완료된 주문 1건을 배송완료 취소시켜줘');
  await page.getByRole('button', { name: '분석' }).click();
  await page.getByRole('link', { name: '실행 이력' }).click();
  await page.getByRole('link', { name: '시나리오 등록', exact: true }).click();
  await expect(page.getByRole('heading', { name: '시나리오 미리보기' })).toBeVisible();
  await expect(page.getByLabel('자연어 요청')).toHaveValue('배송완료된 주문 1건을 배송완료 취소시켜줘');
});
