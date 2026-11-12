// 시나리오 등록(확인용) — 자연어 요청 → ①②③ 분석 결과를 모두 보여 주고, 승인하면 승인본을 고정해 혜정 IR 영역이 IR 을 만든다.
// 승인 판단은 서버가 자기가 계산한 결과로 한다 (화면 값은 믿지 않음). 화면 밖 저장소라 메뉴를 옮겨도 남는다.
import { ApiError, post, type Schemas } from '../../api/client';
import { createStore } from '../../lib/store';
import { generate, setOption } from './ir/irStore';

export type Analysis = Schemas['AnalyzeResult'] & { stopRetry: boolean };
export type AnalysisError = { error: string; trace?: Schemas['Trace'] | null };

/** 승인 결과 줄 — 확인 중 · 거부 · 고정함(IR 생성 시작 여부) · 연결 실패 */
export type ApproveNote =
  | { kind: 'checking' }
  | { kind: 'refused'; error: string }
  | { kind: 'done'; started: boolean; warn?: string }
  | { kind: 'offline'; error: string };

export interface InspectState {
  name: string;
  utterance: string;
  stopRetry: boolean;
  busy: boolean;
  message: string;
  analysis: Analysis | AnalysisError | null;
  /** 단계 key → 직접 확인함 */
  checked: Record<string, boolean>;
  approved: { approval: Schemas['Approval']; file: string } | null;
  note: ApproveNote | null;
}

const empty = () => ({ busy: false, analysis: null, checked: {}, approved: null, note: null });

export const inspect = createStore<InspectState>(() => ({
  name: '',
  utterance: '',
  stopRetry: true,
  message: '',
  ...empty(),
}));

export const isError = (a: InspectState['analysis']): a is AnalysisError =>
  Boolean(a && typeof (a as AnalysisError).error === 'string');

/** '＋ 새 시나리오 등록' — 입력 · 결과를 비운다 */
export const newScenario = () => inspect.set({ name: '', utterance: '', message: '', ...empty() });

/** ①②③ 분석 (진행 줄 없이 결과 하나). 요청이 비었는지는 화면이 먼저 본다 */
export async function analyze() {
  const s = inspect.get();
  if (s.busy) return;
  const stopRetry = s.stopRetry;
  inspect.set({ ...empty(), busy: true, message: '' });
  try {
    const j = await post<Schemas['AnalyzeResult']>('/api/register/analyze', {
      utterance: s.utterance.trim(),
      stop_retry: stopRetry,
    });
    // 이름을 적지 않았으면 업무 이름으로
    const name = s.name.trim() || j.tasks.tasks.map((t) => t.action).join(' · ');
    inspect.set({ busy: false, analysis: { ...j, stopRetry }, name });
  } catch (error) {
    if (error instanceof ApiError && error.status > 0)
      inspect.set({ busy: false, analysis: { error: error.message, trace: error.body.trace ?? null } });
    else inspect.set({ busy: false, message: '서버에 연결하지 못했습니다: ' + (error as Error).message });
  }
}

export const setChecked = (key: string, on: boolean) =>
  inspect.set((s) => ({ checked: { ...s.checked, [key]: on } }));

/** 승인 (승인본 고정) — 승인하면 IR 생성 입력이 생기고, 혜정 IR 영역이 그 승인본으로 IR 을 만든다 */
export async function approve(approver: string) {
  const a = inspect.get().analysis;
  if (!a || isError(a)) return;
  inspect.set({ note: { kind: 'checking' } });
  try {
    const j = await post<Schemas['ApproveResult']>('/api/inspect/approve', {
      selection_hash: a.gate.selection_hash,
      approver: approver || '화면',
      scenario: a.gate.need_scenario, // 버튼을 누르는 것이 시나리오 승인
      steps: Object.keys(inspect.get().checked).filter((k) => inspect.get().checked[k]),
    });
    const h = j.ir_handoff;
    inspect.set({
      approved: { approval: j.approval, file: j.file },
      note: h.filename
        ? { kind: 'done', started: true }
        : { kind: 'done', started: false, warn: h.error || 'IR 초안 생성으로 넘기지 못했습니다' },
    });
    if (h.filename) {
      // 중지조건 · 재시도는 분석 때 고른 값을 IR 생성에도 그대로
      setOption('stop_retry', a.stopRetry);
      document.getElementById('scenarioIRDraft')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
      await generate(h.filename);
    }
  } catch (error) {
    if (error instanceof ApiError && error.status > 0)
      inspect.set({ note: { kind: 'refused', error: error.message } });
    else inspect.set({ note: { kind: 'offline', error: (error as Error).message } });
  }
}
