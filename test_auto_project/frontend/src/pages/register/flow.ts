// 시나리오 등록 진행 — 자연어 요청 → ①②③ 분석 → 시나리오 생성(혜정 IR) → 승인 · 등록.
// 상태는 화면 밖(store)에 둔다: 다른 메뉴로 갔다 와도 진행이 이어진다. 새로고침 · 창 닫기만 경고한다 (지금 화면과 같다).
// 서버: POST /api/register/analyze (스트림) · POST /api/register/ir (스트림) · POST /api/register/scenarios
import { ApiError, post, type Schemas } from '../../api/client';
import { irStepsById, type Ir, type IrEvent, type IrStep } from '../../api/ir';
import { postStream } from '../../api/stream';
import type { StepState } from '../../components/Stepper';
import { createStore } from '../../lib/store';
import { LIVE, canBuild, stagesAt, type AnalyzeResult, type StageKey, type StepMap } from './model';

export interface GenerationOptions {
  kb_rag: boolean;
  dependency_projection: boolean;
}

export interface FlowState {
  /** 입력 — 메뉴를 옮겨도 남는다 */
  name: string;
  utterance: string;
  /** 입력 칸 아래 안내 (요청 없음 · 불러오기 실패 …) */
  message: string;
  busy: boolean;
  stages: Partial<Record<StageKey, StepState>>;
  result: AnalyzeResult | null;
  analysisError: string | null;
  stepMap: StepMap[];
  reviewFile: string | null;
  irSteps: Record<string, IrStep>;
  irTotal: number;
  ir: Ir | null;
  irFile: string | null;
  irError: string | null;
  checked: Record<string, boolean>;
  registered: Schemas['RegisteredSummary'] | null;
  regError: string | null;
  regBusy: boolean;
  /** 등록된 시나리오를 보는 중 (읽기 전용) */
  viewingId: string | null;
}

const fresh = () => ({
  busy: false,
  stages: {},
  result: null,
  analysisError: null,
  stepMap: [],
  reviewFile: null,
  irSteps: {},
  irTotal: 0,
  ir: null,
  irFile: null,
  irError: null,
  checked: {},
  registered: null,
  regError: null,
  regBusy: false,
});

export const flow = createStore<FlowState>(() => ({
  name: '',
  utterance: '',
  message: '',
  viewingId: null,
  ...fresh(),
}));

const errorText = (error: unknown) =>
  error instanceof ApiError && error.status === 0 ? '서버에 연결하지 못했어요' : (error as Error).message;

// ─── 실행 — 버튼 잠금 · 새로고침 경고 ─────────────────────────────────────────────────────

const leaving = (event: BeforeUnloadEvent) => event.preventDefault();

async function run(work: () => Promise<void>) {
  if (flow.get().busy) return;
  flow.set({ busy: true });
  window.addEventListener('beforeunload', leaving); // 새로고침 · 창 닫기만 진행을 끊는다 — 메뉴 이동은 계속 돈다
  try {
    await work();
  } finally {
    window.removeEventListener('beforeunload', leaving);
    flow.set({ busy: false });
  }
}

// ─── ①②③ ────────────────────────────────────────────────────────────────────────

type AnalyzeOutcome = AnalyzeResult | { error: string };
const isError = (x: AnalyzeOutcome): x is { error: string } =>
  typeof (x as { error?: unknown }).error === 'string';

async function select(utterance: string): Promise<boolean> {
  flow.set({ stages: { ...stagesAt('intent'), ir: 'wait' } });
  const got: { result?: AnalyzeOutcome } = {};
  let final: AnalyzeOutcome;
  try {
    const plain = await postStream<{ event: string; stage?: StageKey; result?: AnalyzeOutcome }>(
      '/api/register/analyze',
      { utterance, stop_retry: true },
      (ev) => {
        if (ev.event === 'stage' && ev.stage) flow.set({ stages: { ...stagesAt(ev.stage), ir: 'wait' } });
        else if ((ev.event === 'done' || ev.event === 'error') && ev.result) got.result = ev.result;
      },
    );
    final = got.result ?? (plain as AnalyzeOutcome | null) ?? { error: '서버가 결과를 보내지 않았어요' };
  } catch (error) {
    final = { error: errorText(error) };
  }
  const stages = { ...flow.get().stages };
  if (isError(final)) {
    const now = LIVE.find((k) => stages[k] === 'now');
    if (now) stages[now] = 'fail';
    stages.ir = 'off';
    flow.set({ stages, analysisError: final.error });
    return false;
  }
  LIVE.forEach((k) => (stages[k] = 'done'));
  const ok = canBuild(final);
  if (!ok) stages.ir = 'off';
  flow.set({ stages, result: final }); // 시나리오 이름은 사용자가 적는다 — 자동으로 채우지 않는다
  return ok;
}

// ─── 시나리오 생성 (혜정 IR) — 검토 전 초안 → IR. 단계가 끝날 때마다 그 단계 입력값을 채운다 ─────────────

async function buildIr(options: GenerationOptions) {
  const s = flow.get();
  if (!s.result) return;
  flow.set({
    stepMap: [],
    reviewFile: null,
    irSteps: {},
    irTotal: 0,
    ir: null,
    irFile: null,
    irError: null,
    stages: { ...s.stages, ir: 'now' },
  });
  try {
    const got: { done?: { ir: Ir; file?: string | null }; fail?: string } = {};
    const plain = (await postStream<IrEvent>(
      '/api/register/ir',
      { selection_hash: s.result.gate.selection_hash, generation_options: { stop_retry: true, ...options } },
      (ev) => {
        if (ev.event === 'review_draft') {
          const steps = (ev.steps as StepMap[] | undefined) ?? [];
          flow.set({
            stepMap: steps,
            reviewFile: (ev.filename as string | null) ?? null,
            irTotal: steps.length,
          });
        } else if (ev.event === 'scenario_steps') {
          const n = ((ev.steps as unknown[] | undefined) ?? []).length;
          flow.set((st) => ({ irTotal: n || st.irTotal }));
        } else if (ev.event === 'step_preview' && ev.step) {
          const step = ev.step as IrStep;
          flow.set((st) => ({ irSteps: { ...st.irSteps, [ev.step_id as string]: step } }));
        } else if (ev.event === 'generation_complete') got.done = ev.result as typeof got.done;
        else if (ev.event === 'generation_error') got.fail = (ev.error as string | undefined) || '생성 실패';
      },
    )) as { ir?: Ir; file?: string | null; review?: { filename: string | null; steps: StepMap[] } } | null;
    if (!got.done && plain?.ir) {
      got.done = { ir: plain.ir, file: plain.file };
      if (plain.review) flow.set({ stepMap: plain.review.steps, reviewFile: plain.review.filename });
    }
    const result = got.done;
    if (!result) throw new Error(got.fail || '서버가 결과를 보내지 않았어요');
    flow.set((st) => ({
      ir: result.ir,
      irFile: result.file ?? null,
      irSteps: { ...st.irSteps, ...irStepsById(result.ir) }, // 최종 검증 뒤 고친 값
      stages: { ...st.stages, ir: 'done' },
    }));
  } catch (error) {
    flow.set((st) => ({ irError: errorText(error), stages: { ...st.stages, ir: 'fail' } }));
  }
}

// ─── 화면이 부르는 것 ──────────────────────────────────────────────────────────────

/** 분석 → (만들 수 있으면) 시나리오 생성. 요청이 비었는지는 화면이 먼저 본다 */
export function analyze(options: GenerationOptions) {
  const s = flow.get();
  if (s.busy) return Promise.resolve();
  flow.set({ ...fresh(), name: s.registered ? '' : s.name, message: '', viewingId: null }); // 등록을 끝낸 뒤 새로 분석 — 이름도 새로
  const utterance = s.utterance.trim();
  return run(async () => {
    if (await select(utterance)) await buildIr(options);
  });
}

/** 시나리오 생성 실패 뒤 다시 만들기 */
export const rebuild = (options: GenerationOptions) => run(() => buildIr(options));

export function setChecked(key: string, checked: boolean) {
  flow.set((s) => ({ checked: { ...s.checked, [key]: checked } }));
}

/** 승인하고 등록 — 이름 · 승인자는 화면이 먼저 확인한다. 성공하면 true */
export async function register(name: string, approver: string): Promise<boolean> {
  const s = flow.get();
  if (!s.result || s.regBusy) return false;
  flow.set({ regBusy: true, regError: null });
  try {
    const j = await post<Schemas['RegisterResult']>('/api/register/scenarios', {
      selection_hash: s.result.gate.selection_hash,
      name,
      approver,
      steps: Object.keys(s.checked).filter((k) => s.checked[k]),
      review_file: s.reviewFile,
      ir_file: s.irFile,
    });
    flow.set({ registered: j.scenario, regBusy: false });
    return true;
  } catch (error) {
    flow.set({ regError: '등록하지 못했어요: ' + errorText(error), regBusy: false });
    return false;
  }
}

export const openSaved = (id: string) => flow.set({ viewingId: id, message: '' });
export const closeSaved = () => flow.set({ viewingId: null });

/** 등록 시나리오를 지운 뒤 — 보던 것 · 방금 등록한 것이면 비운다 (다시 등록할 수 있게) */
export function forget(id: string) {
  flow.set((s) => ({
    viewingId: s.viewingId === id ? null : s.viewingId,
    registered: s.registered?.id === id ? null : s.registered,
  }));
}
