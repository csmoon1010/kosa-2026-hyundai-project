import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import type { Schemas } from '../../api/client';
import { AppRoutes } from '../../App';
import { renderWithApp } from '../../test/render';
import { ndjsonResponse, server } from '../../test/server';
import {
  APPROVED_FILE,
  analyzeResult,
  approveResult,
  approvedList,
  budget,
  irEvents,
  irFailedEvents,
  irRuns,
  toLines,
  withStepCheck,
} from './fixtures';
import { inspect } from './inspectState';
import InspectPage from './InspectPage';
import { irStore } from './ir/irStore';

function fakeServer(opts: { analyze?: Schemas['AnalyzeResult']; ir?: string[] } = {}) {
  const sent = { analyze: [] as unknown[], approve: [] as unknown[], ir: [] as unknown[], runs: 0 };
  server.use(
    http.post('/api/register/analyze', async ({ request }) => {
      sent.analyze.push(await request.json());
      return HttpResponse.json(opts.analyze ?? analyzeResult());
    }),
    http.get('/api/admin/graphs', () =>
      HttpResponse.json({
        graphs: [{ graph: { id: 'ORD_STAT_GBCD', name: '주문상태', domain: 'od' } }],
        drafts: [],
      }),
    ),
    http.post('/api/inspect/approve', async ({ request }) => {
      sent.approve.push(await request.json());
      return HttpResponse.json(approveResult());
    }),
    http.get('/api/inspect/ir/approved', () => HttpResponse.json(approvedList())),
    http.get('/api/inspect/ir/budget', () => HttpResponse.json(budget())),
    http.post('/api/inspect/ir', async ({ request }) => {
      sent.ir.push(await request.json());
      return ndjsonResponse(opts.ir ?? toLines(irEvents()));
    }),
    http.get('/api/inspect/ir/logs', () => {
      sent.runs += 1;
      return HttpResponse.json(irRuns());
    }),
  );
  return sent;
}

async function analyzeOnce(user = userEvent.setup()) {
  await user.type(screen.getByLabelText('자연어 요청'), '배송완료된 주문 1건을 배송완료 취소시켜줘');
  await user.click(screen.getByRole('button', { name: '분석 (의도 → 경로 → API)' }));
  await screen.findByRole('heading', { name: '3단계 에이전트 결과' });
  return user;
}

afterEach(() => {
  inspect.reset();
  irStore.reset();
});

describe('시나리오 등록(확인용) — 분석 · 승인 게이트', () => {
  it('①②③ 결과 카드 · 이름은 업무 이름으로 · 도메인 태그', async () => {
    const sent = fakeServer();
    renderWithApp(<InspectPage />);
    await analyzeOnce();
    expect(sent.analyze).toEqual([
      { utterance: '배송완료된 주문 1건을 배송완료 취소시켜줘', stop_retry: true },
    ]);
    expect(screen.getByRole('heading', { name: '배송완료취소' })).toBeInTheDocument(); // 이름 없음 → 업무 이름
    expect(screen.getByLabelText('시나리오 이름')).toHaveValue('배송완료취소');
    expect(screen.getByText('주문', { selector: '.tag' })).toBeInTheDocument();
    expect(screen.getByText(/중지조건 · 재시도 켬 · 전체/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '① 자연어 업무 의도 분석' })).toBeInTheDocument();
    expect(await screen.findByText('주문상태')).toBeInTheDocument(); // ② 그래프 이름
    expect(screen.getByText('경로 있음')).toBeInTheDocument();
    expect(screen.getByText(/경로: 배송완료 → 출고/)).toBeInTheDocument();
    expect(screen.getAllByText('선택', { selector: 'span' })).toHaveLength(2); // ③ 선택 알약
    expect(screen.getByText('① 의도 분석 출력 JSON 전체 보기')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '승인 게이트 — 권한 등급' })).toBeInTheDocument();
  });

  it('승인하면 승인본을 고정하고, 그 승인본으로 IR 생성을 바로 시작한다 (중지조건 · 재시도는 분석 때 값)', async () => {
    const sent = fakeServer();
    renderWithApp(<InspectPage />);
    const user = userEvent.setup();
    await user.click(screen.getByLabelText('중지조건 · 재시도 (①②③ · IR 생성)')); // 끔
    await analyzeOnce(user);
    expect(screen.getByText('끔')).toBeInTheDocument();
    await user.type(screen.getByLabelText('승인자'), '지은');
    await user.click(screen.getByRole('button', { name: '승인 (승인본 고정)' }));
    expect(await screen.findByText('승인본을 고정했어요.')).toBeInTheDocument();
    expect(sent.approve).toEqual([
      { selection_hash: analyzeResult().gate.selection_hash, approver: '지은', scenario: true, steps: [] },
    ]);
    expect(screen.getByText(/✓ 승인 권지은/)).toBeInTheDocument(); // 서버 응답의 승인 기록
    await screen.findByText('IR 초안 저장 완료 · 실행용 시나리오에는 등록하지 않았습니다.');
    expect(sent.ir).toEqual([
      {
        approved_filename: APPROVED_FILE(),
        generation_options: { stop_retry: false, kb_rag: false, dependency_projection: false },
      },
    ]);
  });

  it('단계를 직접 확인해야 승인 버튼이 켜진다', async () => {
    fakeServer({ analyze: withStepCheck() });
    renderWithApp(<InspectPage />);
    const user = await analyzeOnce();
    const button = screen.getByRole('button', { name: '승인 (승인본 고정)' });
    expect(button).toBeDisabled();
    await user.click(screen.getByLabelText('단계 1-1 의 API 가 맞는지 직접 확인했음'));
    expect(button).toBeEnabled();
  });

  it('서버가 승인을 거부하면 그 문구', async () => {
    fakeServer();
    server.use(
      http.post('/api/inspect/approve', () =>
        HttpResponse.json({ error: '시나리오 승인이 필요합니다', refused: true }, { status: 400 }),
      ),
    );
    renderWithApp(<InspectPage />);
    const user = await analyzeOnce();
    await user.click(screen.getByRole('button', { name: '승인 (승인본 고정)' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('✗ 승인 불가');
    expect(alert).toHaveTextContent('시나리오 승인이 필요합니다');
  });

  it('분석이 멈추면 멈춤 카드 (트레이스 요약)', async () => {
    fakeServer();
    const trace = analyzeResult().trace;
    server.use(
      http.post('/api/register/analyze', () =>
        HttpResponse.json({ error: '업무를 찾지 못했습니다', trace }, { status: 400 }),
      ),
    );
    renderWithApp(<InspectPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('자연어 요청'), '안녕');
    await user.click(screen.getByRole('button', { name: '분석 (의도 → 경로 → API)' }));
    expect(await screen.findByRole('heading', { name: '3단계 분석 — 멈춤' })).toBeInTheDocument();
    expect(screen.getByText('업무를 찾지 못했습니다')).toBeInTheDocument();
    expect(screen.getByText(/트레이스: .* · LLM 2회/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '승인 게이트 — 권한 등급' })).not.toBeInTheDocument();
  });

  it('요청이 비었으면 안내 · 새 시나리오 등록은 입력 · 결과를 비운다', async () => {
    fakeServer();
    renderWithApp(<AppRoutes />, '/inspect');
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '분석 (의도 → 경로 → API)' }));
    expect(screen.getByText('자연어 요청을 입력하세요.')).toBeInTheDocument();
    await analyzeOnce(user);
    await user.click(screen.getByRole('button', { name: '＋ 새 시나리오 등록' }));
    expect(screen.queryByRole('heading', { name: '3단계 에이전트 결과' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('자연어 요청')).toHaveValue('');
    expect(screen.getByLabelText('자연어 요청')).toHaveFocus();
  });
});

describe('시나리오 등록(확인용) — 혜정 IR 영역', () => {
  it('처음 열면 첫 승인본의 예산 · 누적 실행 기록', async () => {
    fakeServer();
    renderWithApp(<InspectPage />);
    expect(await screen.findByText(/^STEP 2개 · LLM 12회 · 토큰 130,000 · 시간 150초/)).toBeInTheDocument();
    expect(screen.getByLabelText('저장된 승인본')).toHaveValue(APPROVED_FILE());
    expect(await screen.findByText('JSONL 로그 3 / 3개 · 최신 실행부터 표시')).toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: 'JSONL' });
    expect(links[0]).toHaveAttribute('href', expect.stringMatching(/^\/api\/inspect\/ir\/logs\/IRRUN-/));
  });

  it('IR 다시 생성 — 진행 로그 · STEP · 결과 IR, 행을 고르면 요청 / 응답', async () => {
    const sent = fakeServer();
    renderWithApp(<InspectPage />);
    const user = userEvent.setup();
    const generate = await screen.findByRole('button', { name: 'IR 다시 생성' });
    await waitFor(() => expect(generate).toBeEnabled());
    await user.click(generate);
    const before = sent.runs;
    await screen.findByText('IR 초안 저장 완료 · 실행용 시나리오에는 등록하지 않았습니다.');
    await waitFor(() => expect(sent.runs).toBeGreaterThan(before)); // 생성이 끝나면 누적 실행 기록을 다시 받는다

    expect(screen.getByText(/결과 옵션: 중지조건·재시도/)).toBeInTheDocument();
    expect(screen.getByText(/^전체 로그: .*IRRUN-.*\.jsonl/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'JSONL 다운로드' })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: '시나리오 단계 선택' });
    expect(within(nav).getAllByRole('button')).toHaveLength(2);
    expect(within(nav).getAllByRole('button')[0]).toHaveTextContent('초안 완료 · 확인 필요');

    // 로그 표 30행 — 첫 행이 골라져 있다
    const logTable = screen.getAllByRole('table').find((t) => within(t).queryByText('토큰 이번 / 누적'))!;
    expect(within(logTable).getAllByRole('row')).toHaveLength(31);
    expect(
      screen.getByRole('heading', { name: /선택한 로그 · 백엔드 · STEP 1-1 · Canonical · 백엔드/ }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '1턴 STEP 1-1 LLM 상세 보기' }));
    expect(screen.getByRole('heading', { name: '선택한 로그 · 1턴 · STEP 1-1 · LLM' })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: '요청 프롬프트 / 인자' }));
    expect(screen.getByText('LLM 프롬프트 · JSON · 2칸 들여쓰기 · 응답 수신')).toBeInTheDocument();

    // STEP 상세 · XML 탭(키보드)
    await user.click(within(nav).getAllByRole('button')[1]!);
    expect(screen.getByRole('heading', { name: 'STEP 1-2 · 배송완료취소' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '대체 파라미터' })).toBeInTheDocument();
    const after = screen.getByRole('tab', { name: '적용 후 미리보기' });
    expect(after).toHaveAttribute('aria-selected', 'true');
    after.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: '원본 Baseline' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: '원본 Baseline' })).toHaveFocus();

    expect(screen.getByText(/ v1 · .* · 저장: data\/out\/scenario_ir_drafts\//)).toBeInTheDocument();
    expect(screen.getByText('IR JSON · Beautify')).toBeInTheDocument();
  });

  it('생성이 실패하면 상태 · 실패한 옵션 · STEP 이 실패로', async () => {
    fakeServer({ ir: toLines(irFailedEvents()) });
    renderWithApp(<InspectPage />);
    const user = userEvent.setup();
    const generate = await screen.findByRole('button', { name: 'IR 다시 생성' });
    await waitFor(() => expect(generate).toBeEnabled());
    await user.click(generate);
    expect(
      await screen.findByText(
        /^IR 생성 실패: 정지·재시도 정책에 따라 중단했습니다.* · 승인 파일은 유지됩니다\.$/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/^실패한 실행 옵션:/)).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: '시나리오 단계 선택' });
    expect(within(nav).getAllByRole('button')[0]).toHaveTextContent('생성 실패');
    expect(generate).toBeEnabled(); // 다시 생성할 수 있다
  });

  it('누적 실행 기록 — 날짜 · 옵션 조합으로 거르기', async () => {
    fakeServer();
    renderWithApp(<InspectPage />);
    const user = userEvent.setup();
    await screen.findByText('JSONL 로그 3 / 3개 · 최신 실행부터 표시');
    await user.click(screen.getByLabelText('선택한 조합만 표시'));
    expect(screen.getByText('필터 조건에 맞는 실행 로그가 없습니다. (0 / 3)')).toBeInTheDocument();
    const filters = screen.getByLabelText('실행 기록 필터');
    await user.click(within(filters).getByLabelText('중지조건·재시도'));
    expect(screen.getByText('JSONL 로그 2 / 3개 · 최신 실행부터 표시')).toBeInTheDocument();
    await user.click(within(filters).getByLabelText('압축 1 · 조건별 ParameterKB 검색'));
    expect(screen.getByText('JSONL 로그 1 / 3개 · 최신 실행부터 표시')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '필터 초기화' }));
    fireEvent.change(within(filters).getByLabelText('시작일'), { target: { value: '2026-11-13' } });
    expect(screen.getByText('필터 조건에 맞는 실행 로그가 없습니다. (0 / 3)')).toBeInTheDocument();
  });
});
