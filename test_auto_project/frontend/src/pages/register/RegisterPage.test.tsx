import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Schemas } from '../../api/client';
import { renderWithApp } from '../../test/render';
import { ndjsonResponse, server } from '../../test/server';
import {
  UTTERANCE,
  analyzeResult,
  analyzeStream,
  blocked,
  environment,
  irEvents,
  irFile,
  irStream,
  operations,
  record,
  registerResult,
  reviewFile,
  scenarioList,
  withConfirm,
} from './fixtures';
import { flow } from './flow';
import RegisterPage from './RegisterPage';

/** 서버 흉내 — 등록하면 목록에 생긴다. 요청 본문은 sent 에 */
function fakeServer(opts: { analyze?: string[]; ir?: string[]; catalog?: number } = {}) {
  const sent = {
    analyze: [] as unknown[],
    ir: [] as unknown[],
    register: [] as unknown[],
    delete: [] as unknown[],
  };
  let list: Schemas['RegisteredSummary'][] = [];
  server.use(
    http.get('/api/register/scenarios', () => HttpResponse.json({ scenarios: list })),
    http.get('/api/admin/environment', () => HttpResponse.json(environment(opts.catalog))),
    http.get('/api/admin/operations', () => HttpResponse.json(operations())),
    http.post('/api/register/analyze', async ({ request }) => {
      sent.analyze.push(await request.json());
      return ndjsonResponse(opts.analyze ?? analyzeStream());
    }),
    http.post('/api/register/ir', async ({ request }) => {
      sent.ir.push(await request.json());
      return ndjsonResponse(opts.ir ?? irStream());
    }),
    http.post('/api/register/scenarios', async ({ request }) => {
      sent.register.push(await request.json());
      list = scenarioList().scenarios;
      return HttpResponse.json(registerResult());
    }),
    http.get('/api/register/scenarios/:id', () => HttpResponse.json(record())),
    http.delete('/api/register/scenarios/:id', ({ params }) => {
      sent.delete.push(params.id);
      list = [];
      return HttpResponse.json({ ok: true });
    }),
  );
  return { sent, setList: (l: Schemas['RegisteredSummary'][]) => (list = l) };
}

async function fillAndAnalyze(name = '배송완료 취소') {
  const user = userEvent.setup();
  if (name) await user.type(screen.getByLabelText('시나리오 이름'), name);
  await user.type(screen.getByLabelText('자연어 요청'), UTTERANCE);
  await user.click(screen.getByRole('button', { name: '분석' }));
  return user;
}

const stepStates = () =>
  within(screen.getByRole('list', { name: '진행 단계' }))
    .getAllByRole('listitem')
    .map((li) => li.getAttribute('data-s'));

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    // 막혀 있어도 된다
  }
});
afterEach(() => flow.reset());

describe('시나리오 등록', () => {
  it('요청 → 분석 → 시나리오 생성 → 승인 · 등록 → 목록에 보인다', async () => {
    const { sent } = fakeServer();
    renderWithApp(<RegisterPage />);
    expect(await screen.findByText(/등록된 시나리오가 없습니다/)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '분석' }));
    expect(screen.getByRole('status')).toHaveTextContent('자연어 요청을 입력하세요.');
    expect(screen.getByLabelText('자연어 요청')).toHaveFocus();

    await user.click(screen.getByLabelText('압축 1 · 조건별 ParameterKB 검색'));
    await fillAndAnalyze();
    expect(await screen.findByRole('heading', { name: '시나리오 미리보기' })).toBeInTheDocument();
    await waitFor(() => expect(stepStates()).toEqual(['done', 'done', 'done', 'done']));
    expect(sent.analyze).toEqual([{ utterance: UTTERANCE, stop_retry: true }]);
    expect(sent.ir).toEqual([
      {
        selection_hash: analyzeResult().gate.selection_hash,
        generation_options: { stop_retry: true, kb_rag: true, dependency_projection: false },
      },
    ]);

    // 업무는 설명 문장 · 태그, 단계 카드 · 입력값 표 (필드설명은 명세의 한글 이름)
    expect(screen.getByText('배송완료된 주문')).toBeInTheDocument();
    expect(screen.getByText('주문')).toHaveClass('tag');
    expect(screen.getByText('배송완료 데이터 찾기')).toBeInTheDocument();
    expect(screen.getByText('배송완료 → 출고')).toBeInTheDocument();
    expect(screen.getAllByRole('table')).toHaveLength(3); // 등록 목록 + 단계 2개
    expect(screen.getAllByText('사용자ID').length).toBeGreaterThan(0);
    expect(screen.getAllByText('정해지지 않음').length).toBe(25);
    expect(screen.getByText(/메모 25개/)).toBeInTheDocument();

    await user.type(screen.getByLabelText('승인자'), '지은');
    await user.click(screen.getByRole('button', { name: '승인하고 등록' }));
    expect(await screen.findByText('✓ 등록했어요 — 배송완료 취소')).toBeInTheDocument();
    expect(sent.register).toEqual([
      {
        selection_hash: analyzeResult().gate.selection_hash,
        name: '배송완료 취소',
        approver: '지은',
        steps: [],
        review_file: reviewFile(),
        ir_file: irFile(),
      },
    ]);
    expect(await screen.findByRole('row', { name: '배송완료 취소 보기' })).toBeInTheDocument();
    expect(window.localStorage.getItem('tdg.approver')).toBe('지은');
    expect(window.localStorage.getItem('tdg.opt.kb_rag')).toBe('1');
  });

  it('확인할 것이 있으면 모두 체크해야 등록 — 체크한 단계를 보낸다', async () => {
    const { sent } = fakeServer({ analyze: analyzeStream(withConfirm()) });
    renderWithApp(<RegisterPage />);
    const user = await fillAndAnalyze();
    await waitFor(() => expect(stepStates()[3]).toBe('done'));

    expect(screen.getByText('확인 필요')).toBeInTheDocument();
    expect(screen.getByText('되돌릴 수 없음')).toBeInTheDocument();
    expect(screen.getByText('되돌릴 수 없는 단계는 실행할 때마다 다시 확인해요.')).toBeInTheDocument();
    expect(screen.getByText(/단계 2개 · 되돌릴 수 없는 단계 1개 · 확인할 것 1개/)).toBeInTheDocument();
    expect(screen.getByText('LLM 이 고른 API — 확인 필요')).toBeInTheDocument();

    await user.type(screen.getByLabelText('승인자'), '지은');
    const button = screen.getByRole('button', { name: '승인하고 등록' });
    expect(button).toBeDisabled();
    expect(screen.getByText('확인할 것을 모두 체크하면 등록할 수 있어요.')).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: /업무 1 · 단계 2/ }));
    expect(button).toBeEnabled();
    await user.click(button);
    await screen.findByText('✓ 등록했어요 — 배송완료 취소');
    expect((sent.register[0] as { steps: string[] }).steps).toEqual(['1-1']);
  });

  it('이름 · 승인자가 없으면 등록하지 않고 그 칸으로', async () => {
    const { sent } = fakeServer();
    renderWithApp(<RegisterPage />);
    const user = await fillAndAnalyze('');
    const button = await screen.findByRole('button', { name: '승인하고 등록' });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    expect(screen.getByText('시나리오 이름을 적으세요.')).toBeInTheDocument();
    expect(screen.getByLabelText('시나리오 이름')).toHaveFocus();
    await user.type(screen.getByLabelText('시나리오 이름'), '취소');
    await user.click(button);
    expect(screen.getByText('승인자를 적으세요.')).toBeInTheDocument();
    expect(screen.getByLabelText('승인자')).toHaveFocus();
    expect(sent.register).toEqual([]);
  });

  it('차단이면 멈춤 카드 — 시나리오를 만들지 않는다', async () => {
    const { sent } = fakeServer({ analyze: analyzeStream(blocked()) });
    renderWithApp(<RegisterPage />);
    await fillAndAnalyze();
    expect(await screen.findByRole('heading', { name: '이 요청은 등록할 수 없어요' })).toBeInTheDocument();
    expect(screen.getByText('1-1 출고취소처리: R3 — 실행 금지 API')).toBeInTheDocument();
    expect(stepStates()).toEqual(['done', 'done', 'done', 'off']);
    expect(sent.ir).toEqual([]);
  });

  it('분석이 실패하면 서버 문구 그대로 · 다시 분석', async () => {
    fakeServer({ analyze: analyzeStream({ error: 'GoalError: 업무를 찾지 못했습니다' }) });
    renderWithApp(<RegisterPage />);
    const user = await fillAndAnalyze();
    expect(await screen.findByRole('heading', { name: '분석하지 못했어요' })).toBeInTheDocument();
    expect(screen.getByText('업무를 찾지 못했습니다')).toBeInTheDocument();
    expect(stepStates()).toEqual(['done', 'done', 'fail', 'off']);

    fakeServer();
    await user.click(screen.getByRole('button', { name: '다시 분석' }));
    expect(await screen.findByRole('heading', { name: '시나리오 미리보기' })).toBeInTheDocument();
  });

  it('서버가 요청을 거부하면 (400) 그 문구로 멈춘다', async () => {
    fakeServer();
    server.use(
      http.post('/api/register/analyze', () =>
        HttpResponse.json({ error: '자연어 요청이 비어 있습니다' }, { status: 400 }),
      ),
    );
    renderWithApp(<RegisterPage />);
    await fillAndAnalyze();
    expect(await screen.findByText('자연어 요청이 비어 있습니다')).toBeInTheDocument();
  });

  it('시나리오 생성이 실패하면 다시 만들기 — 등록은 막힌다', async () => {
    const failed = irEvents()
      .slice(0, 1)
      .concat({ event: 'generation_error', error: 'RuntimeError: 예산 초과 [BUDGET]' });
    fakeServer({ ir: irStream(failed) });
    renderWithApp(<RegisterPage />);
    const user = await fillAndAnalyze();
    expect(await screen.findByText('시나리오를 만들지 못했어요')).toBeInTheDocument();
    expect(screen.getByText('예산 초과')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '승인하고 등록' })).toBeDisabled();
    expect(screen.getByText('시나리오를 만든 뒤 등록할 수 있어요.')).toBeInTheDocument();

    fakeServer();
    await user.click(screen.getByRole('button', { name: '다시 만들기' }));
    await waitFor(() => expect(screen.queryByText('시나리오를 만들지 못했어요')).not.toBeInTheDocument());
    expect(stepStates()[3]).toBe('done');
  });

  it('등록된 시나리오 열기(읽기 전용) · 닫기 · 두 번 눌러 삭제', async () => {
    const { sent, setList } = fakeServer();
    setList(scenarioList().scenarios);
    renderWithApp(<RegisterPage />);
    const user = userEvent.setup();
    const row = await screen.findByRole('row', { name: '배송완료 취소 보기' });
    expect(within(row).getByText('등록')).toBeInTheDocument();

    await user.click(row);
    expect(await screen.findByRole('heading', { name: '배송완료 취소' })).toBeInTheDocument();
    expect(screen.getByText('✓ 등록됨 — 승인 지은 · 2026-11-12 21:19')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '승인하고 등록' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '닫기' }));
    expect(screen.queryByRole('heading', { name: '배송완료 취소' })).not.toBeInTheDocument();

    row.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('heading', { name: '배송완료 취소' })).toBeInTheDocument();

    await user.click(within(row).getByRole('button', { name: '삭제' }));
    expect(sent.delete).toEqual([]);
    await user.click(within(row).getByRole('button', { name: '삭제 확인' }));
    await waitFor(() => expect(sent.delete).toEqual([record().id]));
    expect(await screen.findByText(/등록된 시나리오가 없습니다/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '배송완료 취소' })).not.toBeInTheDocument();
  });

  it('API Catalog 가 바뀌었으면 재승인 필요', async () => {
    const { setList } = fakeServer({ catalog: 4 });
    setList(scenarioList().scenarios);
    renderWithApp(<RegisterPage />);
    const row = await screen.findByRole('row', { name: '배송완료 취소 보기' });
    expect(await within(row).findByText('재승인 필요')).toBeInTheDocument();
  });

  it('다른 메뉴로 갔다 와도 결과 · 입력이 남는다', async () => {
    fakeServer();
    const first = renderWithApp(<RegisterPage />);
    await fillAndAnalyze();
    await screen.findByRole('heading', { name: '시나리오 미리보기' });
    first.unmount();

    renderWithApp(<RegisterPage />);
    expect(screen.getByRole('heading', { name: '시나리오 미리보기' })).toBeInTheDocument();
    expect(screen.getByLabelText('자연어 요청')).toHaveValue(UTTERANCE);
    expect(screen.getByLabelText('시나리오 이름')).toHaveValue('배송완료 취소');
  });
});
