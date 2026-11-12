// 혜정 IR 영역 — 승인본 고르기 · 생성 옵션 · 예산 · IR 생성 진행 (web/scenario-ir-draft.js 의 refresh · loadBudget · generate).
// 승인본 목록 · 예산은 생성을 시작할 때 다시 읽는 순서에 묶여 있어 진행 상태와 같은 저장소에 둔다 (누적 실행 기록은 TanStack Query).
// 화면 밖 저장소라 다른 메뉴로 갔다 와도 생성이 이어진다.
import { ApiError, get, type Schemas } from '../../../api/client';
import type { Ir } from '../../../api/ir';
import { postStream } from '../../../api/stream';
import { createStore } from '../../../lib/store';
import {
  applyEvent,
  budgetText,
  describeOptions,
  emptyLog,
  emptyOptions,
  ensureStep,
  failRows,
  resultOptions,
  updateSteps,
  withLogFile,
  type GenerationOptions,
  type IrBudget,
  type IrLog,
  type XmlPreview,
} from './irLog';

export interface IrResult {
  ir: Ir & { scenario_id?: string; version?: unknown; status?: string; generation?: Record<string, unknown> };
  file?: string | null;
  usage?: unknown;
  step_previews?: Record<string, XmlPreview>;
  log_file?: string | null;
  log_url?: string | null;
}

export interface IrState {
  loaded: boolean;
  defaultOptions: GenerationOptions;
  options: GenerationOptions;
  files: Schemas['ApprovedFile'][];
  selected: string;
  budget: IrBudget | null;
  /** 예산 줄 — 산정 결과 · 산정 중 · 오류 */
  settings: string;
  busy: boolean;
  status: string;
  /** 생성 시작 · 끝 시각 (진행 줄 · 진행 중 행의 경과 시간) */
  started: number;
  ended: number;
  log: IrLog;
  detailTab: 'request' | 'response';
  xmlView: 'after' | 'before';
  result: IrResult | null;
}

export const irStore = createStore<IrState>(() => ({
  loaded: false,
  defaultOptions: emptyOptions(),
  options: emptyOptions(),
  files: [],
  selected: '',
  budget: null,
  settings: '',
  busy: false,
  status: '',
  started: 0,
  ended: 0,
  log: emptyLog(),
  detailTab: 'response',
  xmlView: 'after',
  result: null,
}));

const pick = (o: Partial<GenerationOptions>): GenerationOptions => ({
  stop_retry: Boolean(o.stop_retry),
  kb_rag: Boolean(o.kb_rag),
  dependency_projection: Boolean(o.dependency_projection),
});

// ─── 승인본 · 예산 ──────────────────────────────────────────────────────────────────────

let budgetRequest = 0;

/** 고른 승인본의 예산 — 늦게 온 응답은 버린다 */
export async function loadBudget() {
  const request = ++budgetRequest;
  const filename = irStore.get().selected;
  irStore.set({ budget: null, settings: filename ? '예산 산정 중…' : 'STEP 문서 로드 필요' });
  if (!filename) return;
  try {
    const data = await get<Schemas['BudgetResult']>(
      '/api/inspect/ir/budget?filename=' + encodeURIComponent(filename),
    );
    if (request !== budgetRequest) return;
    irStore.set({ budget: data.budget, settings: budgetText(data.budget) });
  } catch (error) {
    if (request === budgetRequest) {
      irStore.set({ settings: (error as Error).message || '예산 산정 실패' });
      throw error;
    }
  }
}

/** 승인본 목록을 다시 읽고 (처음이면 생성 기본값도) 예산을 산정한다. selected 를 주면 그것을 고른다 */
export async function refresh(selected?: string) {
  let data: Schemas['ApprovedList'];
  try {
    data = await get<Schemas['ApprovedList']>('/api/inspect/ir/approved');
  } catch {
    throw new Error('승인본 목록 조회 실패');
  }
  const s = irStore.get();
  if (!s.loaded) {
    const defaults = pick(
      Object.keys(data.default_generation_options).length
        ? data.default_generation_options
        : { stop_retry: data.default_generation_mode === 'validated' },
    );
    irStore.set({
      loaded: true,
      defaultOptions: defaults,
      options: defaults,
      settings: 'STEP 문서 로드 필요',
    });
  }
  const files = data.files.filter((x) => x.approval_status === 'approved');
  const before = selected || irStore.get().selected;
  // 예전 화면(select) 과 같게 — 고른 것이 목록에 없으면 비고, 고른 것이 없으면 첫 승인본
  const chosen = before
    ? files.some((f) => f.filename === before)
      ? before
      : ''
    : (files[0]?.filename ?? '');
  irStore.set({ files, selected: chosen });
  await loadBudget();
}

export function choose(filename: string) {
  irStore.set({ selected: filename });
  loadBudget().catch((e: Error) => irStore.set({ status: e.message }));
}

export const setOption = (key: keyof GenerationOptions, on: boolean) =>
  irStore.set((s) => ({ options: { ...s.options, [key]: on } }));

export const resetOptions = () => irStore.set((s) => ({ options: s.defaultOptions }));

// ─── 생성 ────────────────────────────────────────────────────────────────────────────

function onEvent(event: Record<string, unknown>) {
  irStore.set((s) => ({
    log: applyEvent(s.log, event, Date.now()),
    ...(event.budget
      ? { budget: event.budget as IrBudget, settings: budgetText(event.budget as IrBudget) }
      : {}),
  }));
}

/** 생성 결과 — STEP 을 IR 로 다시 채우고 IR JSON 을 둔다 (preview) */
function preview(data: IrResult) {
  irStore.set((s) => {
    let log = { ...s.log, modeStatus: '결과 옵션: ' + describeOptions(resultOptions(data.ir.generation)) };
    for (const task of (data.ir.tasks ?? []) as {
      sequence?: unknown;
      action?: string;
      conditions?: unknown;
      steps?: { step_id: string; unresolved?: unknown[] }[];
    }[])
      for (const step of task.steps ?? [])
        log = ensureStep(log, {
          step_id: step.step_id,
          step,
          task_sequence: task.sequence,
          task_action: task.action,
          conditions: task.conditions,
          preview: data.step_previews?.[step.step_id],
          status: '초안 완료' + (step.unresolved?.length ? ' · 확인 필요' : ''),
        } as never);
    return { log, result: data };
  });
}

/** IR 다시 생성 — filename 을 주면 그 승인본으로 (확인용 승인 직후) */
export async function generate(filename?: string) {
  if (irStore.get().busy) return;
  const chosenOptions = irStore.get().options;
  irStore.set((s) => ({
    busy: true,
    result: null,
    log: {
      ...emptyLog(),
      activeMode: s.log.activeMode,
      activeOptions: s.log.activeOptions,
      modeStatus: s.log.modeStatus,
    },
    started: Date.now(),
    ended: 0,
  }));
  let activeOptions = chosenOptions;
  try {
    await refresh(filename);
    const chosen = filename || irStore.get().selected;
    if (!chosen) throw new Error('승인본을 선택하세요. 로컬 서버 연결을 확인하세요.');
    if (!irStore.get().budget) throw new Error('예산 산정이 필요합니다');
    activeOptions = { ...chosenOptions };
    const activeMode = activeOptions.stop_retry ? 'validated' : 'basic';
    irStore.set((s) => ({
      options: activeOptions,
      log: {
        ...s.log,
        activeMode,
        activeOptions,
        modeStatus: '실행 옵션: ' + describeOptions(activeOptions),
      },
      status: '승인 JSON 저장 완료 · IR 초안 생성 중…',
    }));
    const got: { result?: IrResult; failure?: string } = {};
    let plain: unknown;
    try {
      plain = await postStream<Record<string, unknown>>(
        '/api/inspect/ir',
        { approved_filename: chosen, generation_options: activeOptions },
        (ev) => {
          if (ev.event === 'generation_complete') {
            const r = ev.result as IrResult;
            got.result = r;
            onEvent({
              event: ev.event,
              file: r.file,
              usage: r.usage,
              log_file: r.log_file,
              log_url: r.log_url,
            });
          } else {
            onEvent(ev);
            if (ev.event === 'generation_error') got.failure = ev.error as string;
          }
        },
      );
    } catch (error) {
      if (error instanceof ApiError) {
        irStore.set((s) => ({ log: withLogFile(s.log, error.body as Record<string, unknown>) }));
        throw new Error(error.body.error || 'IR 생성 HTTP ' + error.status, { cause: error });
      }
      throw error;
    }
    if (got.failure) throw new Error(got.failure);
    const result = got.result ?? (plain as IrResult | null);
    if (!result?.ir) throw new Error('생성 연결이 완료 결과 없이 종료되었습니다. 진행 로그를 확인하세요.');
    irStore.set((s) => ({ log: withLogFile(s.log, result as unknown as Record<string, unknown>) }));
    preview(result);
    irStore.set({ status: 'IR 초안 저장 완료 · 실행용 시나리오에는 등록하지 않았습니다.' });
  } catch (error) {
    const message = (error as Error).message;
    irStore.set((s) => ({
      log: {
        ...failRows(updateSteps(s.log, { event: 'generation_error' }), message, Date.now()),
        modeStatus: '실패한 실행 옵션: ' + describeOptions(activeOptions),
      },
      status: 'IR 생성 실패: ' + message + ' · 승인 파일은 유지됩니다.',
    }));
  } finally {
    irStore.set({ busy: false, ended: Date.now() });
  }
}

// ─── 보기 ────────────────────────────────────────────────────────────────────────────

export const selectRow = (key: string) => irStore.set((s) => ({ log: { ...s.log, selectedKey: key } }));
export const setDetailTab = (tab: 'request' | 'response') => irStore.set({ detailTab: tab });
export const selectStep = (id: string) => irStore.set((s) => ({ log: { ...s.log, selectedStep: id } }));
export const setXmlView = (view: 'after' | 'before') => irStore.set({ xmlView: view });
