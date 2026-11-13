import { expect, test } from '@playwright/test';

// 상태 그래프 만들기 (R5) — 끌어다 놓기 · 잇기 · 이름 · 저장. 임시 data 라 저장소는 그대로
test('그래프 편집기 — 놓기 · 잇기 · 이름 · 저장', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(e.message));

  await page.goto('/admin/order');
  await expect(page.getByRole('combobox', { name: '그래프', exact: true })).toHaveValue('ORD_STAT_GBCD');
  const canvas = page.locator('.react-flow');
  await expect(canvas.locator('.react-flow__node')).toHaveCount(4);
  await expect(canvas.locator('.react-flow__edge')).toHaveCount(6);

  // 공통코드 '10 접수' 를 캔버스 왼쪽 아래로 끌어다 놓기
  const box = (await canvas.boundingBox())!;
  await page
    .getByRole('button', { name: '10 접수' })
    .dragTo(canvas, { targetPosition: { x: box.width * 0.2, y: box.height * 0.8 } });
  await expect(page.getByText('10 접수 을(를) 놓았습니다.')).toBeVisible();
  await expect(canvas.locator('.react-flow__node')).toHaveCount(5);

  // 접수(10)의 ● 을 끌어 출고대기(25) 에 놓아 화살표
  const port = canvas.locator('.react-flow__node[data-id="10"] .react-flow__handle-right');
  const target = canvas.locator('.react-flow__node[data-id="25"]');
  await port.dragTo(target);
  await expect(
    page.getByText('접수 → 출고대기 화살표를 만들었습니다. 업무에서 부르는 이름을 적으세요.'),
  ).toBeVisible();
  await expect(canvas.locator('.react-flow__edge')).toHaveCount(7);

  // 이름 적기
  await page.getByLabel('업무에서 부르는 이름').fill('출고대기전환');
  await page.getByRole('button', { name: '확정' }).click();
  await expect(page.getByText("'출고대기전환' 로 확정했습니다.")).toBeVisible();

  // 저장
  await page.getByRole('button', { name: '저장', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '저장' });
  await expect(dialog.getByText('저장되는 화살표 7개 (이름을 적은 것)')).toBeVisible();
  await dialog.getByRole('button', { name: '확인 후 저장' }).click();
  await expect(page.getByText('승인본 v1 로 저장했습니다 · data/graphs/ORD_STAT_GBCD.yaml')).toBeVisible();

  // 서버에 남았는가 — 화면에서 저장한 그래프(drafts) 에 배치 · 화살표
  const graphs = await (await page.request.get('/api/admin/graphs')).json();
  const saved = graphs.drafts.find((g: { graph: { id: string } }) => g.graph.id === 'ORD_STAT_GBCD');
  expect(saved.version).toBe(1);
  expect(Object.keys(saved.layout)).toContain('10');
  expect(saved.transitions).toContainEqual(
    expect.objectContaining({ name: '출고대기전환', from: '10', to: '25' }),
  );

  // 새로고침해도 저장본으로 다시 연다
  await page.reload();
  await expect(page.locator('.react-flow__node')).toHaveCount(5);
  await expect(page.getByText('승인본 v1')).toBeVisible();

  expect(errors).toEqual([]);
});
