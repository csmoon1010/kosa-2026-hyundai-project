import { expect, test, type Page } from '@playwright/test';

// 화면 점검 2 (docs/fastapi.md 6.3) 를 가짜 LLM 서버로 — 등록 시나리오 담기 → 반복 → 드라이런(입력값 표 · 요청 XML) → 실행 이력
async function registerOne(page: Page, name: string) {
  await page.goto('/register');
  await page.getByLabel('시나리오 이름').fill(name);
  await page.getByLabel('자연어 요청').fill('배송완료된 주문 1건을 배송완료 취소시켜줘');
  await page.getByRole('button', { name: '분석' }).click();
  await expect(page.getByRole('list', { name: '진행 단계' }).getByRole('listitem').last()).toHaveAttribute(
    'data-s',
    'done',
  );
  await page.getByLabel('승인자').fill('테스트');
  await page.getByRole('button', { name: '승인하고 등록' }).click();
  await expect(page.getByText(`✓ 등록했어요 — ${name}`)).toBeVisible();
}

test('시나리오 실행 — 담기 · 드라이런 · 실행 이력', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(e.message));

  await registerOne(page, 'E2E 실행용');
  await page.getByRole('link', { name: '시나리오 실행' }).click();
  await page.getByRole('button', { name: /E2E 실행용/ }).click();
  const repeat = page.getByLabel('반복 횟수');
  await repeat.fill('2');
  await repeat.press('Enter');
  await page.getByRole('button', { name: '드라이런' }).click();

  await expect(page.getByRole('heading', { name: '드라이런 결과' })).toBeVisible();
  await expect(page.getByText('E2E 실행용 #2')).toBeVisible();
  await expect(page.getByText('요청 4건 · 실제 API 는 호출하지 않았어요')).toBeVisible();
  await page.getByText('보낼 요청 XML').first().click();
  await expect(page.locator('pre').first()).toContainText('<Root>');

  await page.getByRole('button', { name: '실행 이력 보기' }).click();
  await expect(page).toHaveURL(/\/history$/);
  const row = page.getByRole('row', { name: /E2E 실행용/ });
  await expect(row).toBeVisible();
  await row.click();
  await expect(page.getByText(/되돌리는 순서:/)).toBeVisible();

  expect(errors).toEqual([]);
});
