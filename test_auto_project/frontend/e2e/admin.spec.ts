import { expect, test } from '@playwright/test';

// 화면 점검 4 (docs/fastapi.md 6.3, 그래프 빼고) — 규칙 추가 · 삭제, Baseline 저장, 다시 빌드, 전처리 갱신. 임시 data 라 저장소는 그대로
test('관리자 — 전사 · 도메인', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(e.message));

  await page.goto('/admin');
  await expect(page).toHaveURL(/\/admin\/all$/);
  await expect(page.getByRole('heading', { name: '1단계 산출물 · 검수 목록' })).toBeVisible();

  // 데이터 조회 팝업 — 전처리 문서 필터
  await page.getByRole('button', { name: /Parameter KB/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Parameter KB' });
  await expect(dialog.getByRole('status')).toHaveText(/^기본 필드 \d+개$/);
  await dialog.getByLabel('도메인 필터').selectOption('ds');
  await expect(dialog.getByRole('heading', { name: '승인된 공통 지식' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();

  // 다시 빌드
  await page.getByRole('button', { name: '전체 변경 확인' }).click();
  await expect(page.getByText(/catalog v\d+/).filter({ hasText: /바뀐 것 없음|다시 빌드/ })).toBeVisible();

  // 도메인 — 규칙 추가 · 삭제
  await page.getByRole('tab', { name: /물류/ }).click();
  await expect(page).toHaveURL(/\/admin\/logistics$/);
  await page.getByLabel('저장 대상').selectOption('meta');
  await page.getByLabel('항목').selectOption('memo');
  await page.getByLabel('구별 메모').fill('E2E 메모 — 단건 처리');
  await page.getByRole('button', { name: '저장 · 적용' }).click();
  await expect(page.getByText(/API MetaData · 구별 메모 저장 — .*다시 빌드/)).toBeVisible();
  await page.getByRole('button', { name: /^등록된 내역 \(\d+\)$/ }).click();
  const hist = page.getByRole('dialog', { name: '등록된 내역' });
  const row = hist.locator('div', { hasText: 'E2E 메모 — 단건 처리' }).last();
  await row.getByRole('button', { name: '삭제' }).click();
  await expect(hist.getByText('E2E 메모 — 단건 처리')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(page.getByText('규칙을 지우고 다시 빌드했습니다.')).toBeVisible();

  // Baseline 저장 (지금 값 그대로)
  await page.getByRole('button', { name: '사용자 등록 · 검증' }).click();
  await expect(page.getByText(/^사용자 등록값 저장 · /)).toBeVisible();

  // 머리 — 전처리 산출물 갱신
  await page.getByRole('button', { name: '전처리 산출물 갱신' }).click();
  await expect(page.getByText(/^전처리 JSON · Canonical \d+/)).toBeVisible();

  expect(errors).toEqual([]);
});
