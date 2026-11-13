import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { renderWithApp } from '../../../test/render';
import { server } from '../../../test/server';
import { admin, adminHandlers } from '../fixtures';
import { editor } from './editorStore';
import { GraphEditor } from './GraphEditor';

function fakeServer(d = admin()) {
  const saved: { id: string; yaml: string }[] = [];
  server.use(
    http.put('/api/admin/graphs/:id', async ({ params, request }) => {
      const body = (await request.json()) as { yaml: string };
      saved.push({ id: String(params.id), yaml: body.yaml });
      return HttpResponse.json({ file: `data/graphs/${params.id}.yaml`, kept: [], backup: null });
    }),
    ...adminHandlers(d),
  );
  return saved;
}

// 화면을 먼저 내린다 — 붙어 있는 편집기가 비운 저장소를 자기 그래프로 다시 채우지 않게
afterEach(() => {
  cleanup();
  editor.reset();
});

const progress = () =>
  screen.getByText((_, el) => el?.tagName === 'SPAN' && /^상태 \d+개 · 화살표/.test(el.textContent ?? ''));

// React Flow 를 그리는 화면이라 jsdom 에서 느리다 — 테스트마다 넉넉히
describe('상태 그래프 만들기', { timeout: 20_000 }, () => {
  it('손으로 쓴 그래프를 자동 배치해 연다 — 공통코드 23개, 화살표 6개 (이름 확정 6)', async () => {
    fakeServer();
    renderWithApp(<GraphEditor dom="od" />);
    expect(
      await screen.findByRole('heading', { name: '상태 그래프 만들기' }, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('그래프')).toHaveValue('ORD_STAT_GBCD');
    expect(screen.getByText(/· 23개$/)).toBeInTheDocument();
    expect(progress()).toHaveTextContent('상태 4개 · 화살표 6개 (이름 확정 6 · 이름 없음 0)');
    expect(screen.getByRole('button', { name: '이름 없음 0' })).toBeDisabled();
  });

  it('공통코드를 누르면 빈 자리에, 놓인 것을 누르면 선택 — Delete 로 캔버스에서 뺀다', async () => {
    fakeServer();
    renderWithApp(<GraphEditor dom="od" />);
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: '상태 그래프 만들기' }, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: '10 접수' }));
    expect(
      screen.getByText('10 접수 을(를) 빈 자리에 놓았습니다. 끌어서 옮길 수 있어요.'),
    ).toBeInTheDocument();
    expect(progress()).toHaveTextContent('상태 5개');
    expect(screen.getByRole('button', { name: '10 접수 · 배치됨' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '45 출고 · 배치됨' })); // 놓인 것 → 선택
    fireEvent.keyDown(screen.getByRole('button', { name: '45 출고' }), { key: 'Delete' });
    expect(
      screen.getByText(/^45 출고 을\(를\) 캔버스에서 뺐습니다 \(화살표 \d+개 함께\)\.$/),
    ).toBeInTheDocument();
    expect(progress()).toHaveTextContent('상태 4개');
  });

  it('할 일에서 화살표를 골라 이름을 바꾼다 — 되돌리는 화살표가 없으면 확인할 일', async () => {
    const d = admin();
    const ord = d.graphs.graphs.find((g) => g.graph.id === 'ORD_STAT_GBCD')!;
    ord.transitions = ord.transitions.filter((t) => t.name !== '배송완료취소');
    fakeServer(d);
    renderWithApp(<GraphEditor dom="od" />);
    const user = userEvent.setup();
    const todo = (
      await screen.findByText(/^출고 → 배송완료: 되돌리는 화살표가 없어/, {}, { timeout: 5000 })
    ).closest('button')!;
    await user.click(todo);
    expect(screen.getByRole('heading', { name: '출고 → 배송완료' })).toBeInTheDocument();
    expect(screen.getByText(/되돌리는 화살표\(배송완료 → 출고\)가 없습니다/)).toBeInTheDocument();
    const input = screen.getByLabelText('업무에서 부르는 이름');
    expect(input).toHaveValue('배송완료');
    await user.clear(input);
    await user.type(input, '배송완료처리{Enter}');
    expect(screen.getByText("'배송완료처리' 로 확정했습니다.")).toBeInTheDocument();
    expect(screen.queryByLabelText('업무에서 부르는 이름')).not.toBeInTheDocument(); // 이름 없는 화살표가 없으면 할 일로
  });

  it('그래프 설정 — 이미 확정된 상태 필드, 시험해 보기 — 출발 → 목표 경로', async () => {
    fakeServer();
    renderWithApp(<GraphEditor dom="od" />);
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: '상태 그래프 만들기' }, { timeout: 5000 });
    await user.click(screen.getByRole('button', { name: '⋯ 더보기' }));
    await user.click(screen.getByRole('menuitem', { name: '그래프 설정 (상태 필드)' }));
    const dialog = screen.getByRole('dialog', { name: '그래프 설정' });
    expect(within(dialog).getByLabelText('조회 결과에서 현재 상태를 읽는 필드')).toHaveValue(
      'lastDlvstPrgrGbcd',
    );
    expect(within(dialog).getByText('확정')).toBeInTheDocument();
    await user.click(within(dialog).getAllByRole('button', { name: '닫기' }).at(-1)!);

    await user.click(screen.getByRole('button', { name: '시험해 보기' }));
    const test = screen.getByRole('dialog', { name: '시험해 보기' });
    expect(within(test).getByLabelText('출발 상태')).toHaveValue('25');
    expect(within(test).getByLabelText('목표 상태')).toHaveValue('50');
    expect(within(test).getByRole('status')).toHaveTextContent(
      '경로25 출고대기 → 출고진행 → 30 출고진행 → 출고완료 → 45 출고 → 배송완료 → 50 배송완료 · 화살표 3개',
    );
    await user.selectOptions(within(test).getByLabelText('출발 상태'), '50');
    await user.selectOptions(within(test).getByLabelText('목표 상태'), '25');
    const again = screen.getByRole('dialog', { name: '시험해 보기' });
    expect(within(again).getByRole('status').textContent).toBe(
      '경로50 배송완료 → 배송완료취소 → 45 출고 → 출고완료취소 → 30 출고진행 → 출고취소 → 25 출고대기 · 화살표 3개',
    );
  });

  it('저장 — 저장될 YAML 을 보여 주고, 승인본 번호를 올려 서버에 보낸다', async () => {
    const saved = fakeServer();
    renderWithApp(<GraphEditor dom="od" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: '저장' }));
    const dialog = screen.getByRole('dialog', { name: '저장' });
    expect(within(dialog).getByText(/^저장되는 화살표/)).toHaveTextContent(
      '저장되는 화살표 6개 (이름을 적은 것)',
    );
    expect(dialog.querySelector('pre')!.textContent).toMatch(
      /^# 주문상태 그래프 — 화면에서 저장 \(저장 전 미리보기\)/,
    );
    await user.click(within(dialog).getByRole('button', { name: '확인 후 저장' }));
    expect(
      await screen.findByText('승인본 v1 로 저장했습니다 · data/graphs/ORD_STAT_GBCD.yaml'),
    ).toBeInTheDocument();
    expect(saved).toHaveLength(1);
    expect(saved[0]!.id).toBe('ORD_STAT_GBCD');
    expect(saved[0]!.yaml).toMatch(/^# 주문상태 그래프 — 화면에서 저장 \(승인본 v1\)/);
    expect(saved[0]!.yaml).toContain('\nversion: 1\n');
    expect(saved[0]!.yaml).toContain('  - name: "출고진행"\n    from: "25"\n    to: "30"');
    expect(screen.getByText('승인본 v1')).toBeInTheDocument();
  });

  it('그래프가 없는 도메인 — 새 그래프 (아직 그래프로 안 만든 공통코드 그룹)', async () => {
    fakeServer();
    renderWithApp(<GraphEditor dom="ds" />);
    const user = userEvent.setup();
    expect(await screen.findByText('이 도메인이 주인인 상태 그래프가 없습니다')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '새 그래프' }));
    expect(screen.getByLabelText('공통코드 그룹 — 아직 그래프로 안 만든 것')).toHaveValue('ITEM_SELL_GBCD');
    expect(screen.getByLabelText('담당 도메인 — 상태 코드 그룹의 주인')).toHaveValue('물류 (ds)');
    await user.clear(screen.getByLabelText('그래프 이름'));
    await user.click(screen.getByRole('button', { name: '만들기' }));
    expect(screen.getByText('그래프 이름을 적으세요.')).toBeInTheDocument();
    await user.type(screen.getByLabelText('그래프 이름'), '상품판매');
    await user.click(screen.getByRole('button', { name: '만들기' }));
    await waitFor(() => expect(screen.getByLabelText('그래프')).toHaveValue('ITEM_SELL_GBCD'));
    expect(screen.getByText(/상품판매 그래프를 만들었습니다/)).toBeInTheDocument();
    expect(screen.getByText(/① 왼쪽 공통코드에서 상태를 끌어다 놓고/)).toBeInTheDocument();
  });
});
