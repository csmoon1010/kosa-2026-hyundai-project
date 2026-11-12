import { expect, test } from '@playwright/test';

const MENUS = ['시나리오 등록', '시나리오 등록(확인용)', '시나리오 실행', '실행 이력', '관리자 메뉴'];

test('메뉴 5개 · 가짜 LLM 서버 연결 · 메뉴 이동', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/register$/);
  const nav = page.getByRole('navigation', { name: '메뉴' });
  await expect(nav.getByRole('link')).toHaveText(MENUS);
  await expect(page.getByText('서버 연결됨')).toBeVisible();
  await expect(page.getByText('가짜 LLM')).toBeVisible();

  for (const [label, path] of [
    ['실행 이력', '/history'],
    ['관리자 메뉴', '/admin/all'],
    ['시나리오 실행', '/run'],
  ] as const) {
    await nav.getByRole('link', { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(path + '$'));
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(label);
  }
});

test('새로고침해도 같은 메뉴 — 주소가 메뉴', async ({ page }) => {
  await page.goto('/history');
  await page.reload();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('실행 이력');
});

test('개발 프록시가 진행 스트림(NDJSON)을 줄 단위로 넘긴다', async ({ request }) => {
  const res = await request.post('/api/register/analyze', {
    headers: { Accept: 'application/x-ndjson' },
    data: { utterance: '배송완료된 주문 1건을 배송완료 취소시켜줘' },
  });
  expect(res.ok()).toBe(true);
  expect(res.headers()['content-type']).toContain('application/x-ndjson');
  const lines = (await res.text())
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line));
  expect(lines.map((l) => l.stage ?? l.event)).toEqual(['intent', 'paths', 'apis', 'done']);
  expect(lines.at(-1).result.gate.selection_hash).toMatch(/^sha256:/);
});
