// 혜정 IR 영역 — 생성 진행 이벤트를 로그 행 · STEP 상태로 쌓는 규칙 (web/scenario-ir-draft.js 의 logEvent · updateSteps ·
// ensureStep · progress · renderRow 를 그대로). 화면 그리기와 나눠 순수 함수로 — 같은 이벤트면 같은 결과.
import type { Schemas } from '../../../api/client';

type Json = Record<string, unknown>;
export type IrBudget = Schemas['IrBudget'];
export type GenerationOptions = { stop_retry: boolean; kb_rag: boolean; dependency_projection: boolean };

export const OPTION_LABELS: Record<keyof GenerationOptions, string> = {
  stop_retry: '중지조건·재시도',
  kb_rag: '압축 1 · 조건별 ParameterKB 검색',
  dependency_projection: '압축 2 · 의존성 기반 STEP 문맥 선별',
};
export const OPTION_KEYS = Object.keys(OPTION_LABELS) as (keyof GenerationOptions)[];
export const emptyOptions = (): GenerationOptions => ({
  stop_retry: false,
  kb_rag: false,
  dependency_projection: false,
});

export const describeOptions = (o: Partial<GenerationOptions> | null | undefined) =>
  OPTION_KEYS.filter((k) => o?.[k])
    .map((k) => OPTION_LABELS[k])
    .join(' + ') || '기본 모드';

/** 결과 IR 의 generation 에서 옵션 — 옵션 기록이 없던 예전 결과는 실행 모드로 */
export const resultOptions = (generation: Json | undefined): Partial<GenerationOptions> =>
  (generation?.options as GenerationOptions | undefined) ?? {
    ...emptyOptions(),
    stop_retry: generation?.execution_mode === 'validated',
  };

export const budgetText = (b: IrBudget) =>
  `STEP ${b.step_count}개 · LLM ${b.limits.llm_calls}회 · 토큰 ${b.limits.tokens.toLocaleString()} · 시간 ${b.limits.seconds}초 · 호출당 출력 4,096 · STEP 기본 5회 + 공유 예비 2회 · 절대 상한 40회 / 400,000토큰 / 600초 (수정 불가)`;

// ─── 로그 행 ──────────────────────────────────────────────────────────────────────────

export interface LogRow {
  key: string;
  kind?: 'backend';
  turn?: unknown;
  step_turn?: unknown;
  step_id?: string;
  tool?: string;
  usage?: Json;
  turn_usage?: Json;
  request?: unknown;
  response?: unknown;
  /** 끝난 행의 소요 시간 — 없으면 진행 중 */
  seconds?: number;
  started: number;
  state?: string;
  valid?: boolean;
}

const BACKEND_NAMES: Record<string, string> = {
  kb_retrieval: 'ParameterKB 검색 · 백엔드',
  context_projection: 'STEP 문맥 선별 · 백엔드',
  backend_canonical: 'Canonical · 백엔드',
  backend_baseline_compare: 'Baseline 비교 · 백엔드',
  material_check: '필요 자료 확인 · 백엔드',
  backend_output_defined: '앞 STEP 출력 보완 · 백엔드',
  mapping_validation: 'validate_mapping · 백엔드',
  final_ir_validation: '최종 IR 검증 · 백엔드',
  mapping_repair: '매핑 수정 요청 · 백엔드',
  recovery_stopped: '복구 중단 · 백엔드',
  llm_retry: 'LLM 통신 재시도 · 백엔드',
  llm_attempt_start: 'LLM 통신 시도 · 백엔드',
  llm_attempt_error: 'LLM 통신 오류 · 백엔드',
  llm_attempt_complete: 'LLM 통신 수신 · 백엔드',
};
const ATTEMPTS = ['llm_attempt_start', 'llm_attempt_error', 'llm_attempt_complete'];
const TURN_BACKEND = [
  'mapping_validation',
  'final_ir_validation',
  'mapping_repair',
  'recovery_stopped',
  'llm_retry',
  ...ATTEMPTS,
];

// ─── STEP ─────────────────────────────────────────────────────────────────────────────

export interface StepData {
  step_id: string;
  edge?: string;
  api: Json;
  inputs: Json[];
  bindings: { binding_id?: string; from?: { from_step_id?: string; output_name?: string } }[];
  outputs?: Json[];
  unresolved?: unknown[];
  baseline?: { validation_status?: string };
  [key: string]: unknown;
}

export interface XmlPreview {
  available?: boolean;
  warnings?: string[];
  applied_lines?: { text: string; changed?: boolean }[];
  original_xml?: string;
}

export interface StepEntry {
  id: string;
  s: StepData;
  status: string;
  task_sequence?: unknown;
  task_action?: string;
  conditions?: unknown;
  preview?: XmlPreview;
}

// ─── 전체 ─────────────────────────────────────────────────────────────────────────────

export interface IrLog {
  order: string[];
  rows: Record<string, LogRow>;
  selectedKey: string | null;
  steps: string[];
  entries: Record<string, StepEntry>;
  selectedStep: string | null;
  lastEvent: Json;
  /** 진행 중 실행 모드 — basic · validated */
  activeMode: string;
  activeOptions: GenerationOptions;
  modeStatus: string;
  logFile: { log_file: string; log_url?: string } | null;
}

export const emptyLog = (): IrLog => ({
  order: [],
  rows: {},
  selectedKey: null,
  steps: [],
  entries: {},
  selectedStep: null,
  lastEvent: {},
  activeMode: 'basic',
  activeOptions: emptyOptions(),
  modeStatus: '',
  logFile: null,
});

/** 로그 파일 위치 — 실패 응답 · 이벤트 어디서 와도 */
export function withLogFile(log: IrLog, data: Json | null | undefined): IrLog {
  if (!data?.log_file) return log;
  return {
    ...log,
    logFile: { log_file: String(data.log_file), log_url: data.log_url as string | undefined },
  };
}

type StepMeta = Json & {
  step_id?: string;
  step?: Json & { step_id?: string; api?: Json };
  api?: Json;
  edge?: string;
};

/** STEP 을 만들거나 고친다 (ensureStep). 새로 만든 첫 STEP 은 고른 STEP 이 된다 */
export function ensureStep(log: IrLog, meta: StepMeta): IrLog {
  const id = meta.step_id || meta.step?.step_id;
  if (!id) return log;
  let { steps, selectedStep } = log;
  const prior = log.entries[id];
  const entry: StepEntry = prior
    ? { ...prior, s: { ...prior.s } }
    : { id, s: { step_id: id, api: {}, inputs: [], bindings: [] }, status: '대기' };
  if (!prior) {
    steps = [...steps, id];
    if (selectedStep === null) selectedStep = id;
  }
  const priorApi = entry.s.api;
  if (meta.step)
    entry.s = {
      ...entry.s,
      ...(meta.step as Partial<StepData>),
      api: { ...priorApi, ...(meta.step.api ?? {}) },
    };
  if (meta.api) entry.s.api = { ...entry.s.api, ...meta.api };
  if (meta.edge !== undefined) entry.s.edge = meta.edge;
  for (const key of ['task_sequence', 'task_action', 'conditions', 'preview', 'status'] as const)
    if (meta[key] !== undefined) (entry as unknown as Json)[key] = meta[key];
  return { ...log, steps, selectedStep, entries: { ...log.entries, [id]: entry } };
}

/** 진행 이벤트 → STEP 상태 (updateSteps) */
export function updateSteps(log: IrLog, event: Json): IrLog {
  const kind = event.event as string;
  if (kind === 'scenario_steps') {
    return ((event.steps as StepMeta[]) ?? []).reduce(ensureStep, log);
  }
  let entry: StepEntry | null = event.step_id ? (log.entries[event.step_id as string] ?? null) : null;
  const at = (l: IrLog, id: string | undefined) => (id ? (l.entries[id] ?? null) : null);
  if (kind === 'llm_request') {
    try {
      const input = (event.input || event.messages || []) as { role?: string; content?: string }[];
      const payload = JSON.parse(input.find((x) => x.role === 'user')?.content || '{}') as Json;
      const intent = payload.intent_task as Json | undefined;
      if (payload.current_step) {
        const cs = payload.current_step as StepMeta;
        log = ensureStep(log, {
          ...cs,
          task_sequence: intent?.sequence,
          task_action: intent?.action,
          conditions: intent?.conditions,
        });
        entry = at(log, cs.step_id);
      }
    } catch {
      // 프롬프트가 JSON 이 아니면 STEP 을 고치지 않는다
    }
    if (entry) {
      log = ensureStep(log, { step_id: entry.id, status: '분석 중' });
      entry = at(log, entry.id);
    }
  }
  if (kind === 'backend_canonical') {
    log = ensureStep(log, { step_id: event.step_id as string, api: event.result as Json });
    entry = at(log, event.step_id as string);
  }
  if (kind === 'step_complete' && entry) {
    log = ensureStep(log, { step_id: entry.id, status: '초안 작성 · 비교 중', step: event.result as Json });
    entry = at(log, entry.id);
  }
  if (kind === 'backend_baseline_compare' && entry) {
    const comparisons = ((event.result as Json)?.comparisons as Json[]) ?? [];
    log = {
      ...log,
      entries: { ...log.entries, [entry.id]: { ...entry, s: { ...entry.s, inputs: comparisons } } },
    };
  }
  if (kind === 'step_preview') {
    const step = event.step as Json & { unresolved?: unknown[] };
    log = ensureStep(log, {
      ...event,
      status: '초안 완료' + (step?.unresolved?.length ? ' · 확인 필요' : ''),
    } as StepMeta);
  }
  if (kind === 'backend_output_defined') {
    const result = event.result as { step_id?: string; output?: Json & { name?: string } } | undefined;
    const source = result?.step_id ? log.entries[result.step_id] : undefined;
    if (source && result?.output) {
      const outputs = source.s.outputs ?? [];
      if (!outputs.some((o) => o.name === result.output!.name))
        log = {
          ...log,
          entries: {
            ...log.entries,
            [source.id]: { ...source, s: { ...source.s, outputs: [...outputs, result.output] } },
          },
        };
    }
  }
  if (kind === 'generation_error' || kind === 'llm_error') {
    for (const id of log.steps) {
      const item = log.entries[id]!;
      if (['분석 중', '초안 작성 · 비교 중'].includes(item.status))
        log = ensureStep(log, { step_id: id, status: '생성 실패' });
    }
    if (log.activeMode === 'validated')
      for (const id of log.steps) {
        const item = log.entries[id]!;
        if (item.status.startsWith('초안 완료'))
          log = ensureStep(log, { step_id: id, status: '중간 결과 · 전체 생성 실패' });
      }
  }
  return log;
}

/** 진행 이벤트 하나 (logEvent) — 로그 파일 · 실행 옵션 · STEP · 로그 행. 예산(event.budget)은 부르는 쪽이 표시한다 */
export function applyEvent(log: IrLog, event: Json, now: number): IrLog {
  log = withLogFile(log, event);
  if (event.execution_mode) {
    const activeMode = String(event.execution_mode);
    const activeOptions = (event.options as GenerationOptions | undefined) ?? {
      ...log.activeOptions,
      stop_retry: activeMode === 'validated',
    };
    log = { ...log, activeMode, activeOptions, modeStatus: '실행 옵션: ' + describeOptions(activeOptions) };
  }
  log = updateSteps(log, event);
  const lastEvent = { ...log.lastEvent, ...event };
  if (event.event !== 'llm_request') delete lastEvent.next_turn;
  log = { ...log, lastEvent };

  const kind = String(event.event);
  const isTool = kind.startsWith('tool_');
  const isBackend = Boolean(BACKEND_NAMES[kind]);
  const isLLM = kind.startsWith('llm_') || kind === 'validation_feedback' || kind === 'step_complete';
  if (!isTool && !isLLM && !isBackend) return log;
  const turn = event.next_turn || event.turn;
  const isAttempt = ATTEMPTS.includes(kind);
  const key = isBackend
    ? `backend:${event.step_id}:${isAttempt ? 'llm_attempt' : kind}:${event.request_id || event.turn || 0}:${event.attempt || event.step_turn || 0}`
    : isTool
      ? `tool:${event.step_id}:${event.call_id || `${turn}:${event.tool}`}`
      : `llm:${turn}`;

  const prior = log.rows[key];
  const row: LogRow = prior ? { ...prior } : { key, started: now };
  Object.assign(row, {
    turn,
    step_turn: event.step_turn ?? row.step_turn,
    step_id: (event.step_id as string) || row.step_id,
    tool: (event.tool as string) || row.tool,
    usage: (event.usage as Json) || row.usage,
  });
  const result = event.result as Json | undefined;
  if (isBackend) {
    row.kind = 'backend';
    row.tool = BACKEND_NAMES[kind];
    row.turn = '—';
    row.step_turn = '—';
    row.request = event.request ?? (isAttempt ? row.request : undefined);
    row.response = event.result;
    row.seconds = (event.backend_seconds as number | undefined) ?? 0;
    row.state = '완료';
    if (isAttempt) {
      row.tool = `LLM 통신 시도 ${event.attempt} · 백엔드`;
      row.request = event.request ?? row.request;
      if (kind === 'llm_attempt_start') {
        row.seconds = undefined;
        row.state = '통신 중';
      }
    }
    if (TURN_BACKEND.includes(kind)) {
      row.turn = event.turn ?? '—';
      row.step_turn = event.step_turn ?? '—';
    }
    row.valid = typeof result?.valid === 'boolean' ? result.valid : undefined;
    if (result?.valid === false || kind === 'llm_attempt_error') row.state = '검사 / 통신 오류';
    if (kind === 'llm_retry') row.state = '대기 후 재시도';
    if (kind === 'mapping_repair') row.state = '수정 요청';
    if (kind === 'recovery_stopped') row.state = '중단';
  }
  const elapsed = () => (now - row.started) / 1000;
  if (kind === 'llm_request') {
    row.request = event.input
      ? {
          model: event.model,
          instructions: event.instructions,
          input: event.input,
          tools: event.tools,
          tool_choice: event.tool_choice,
          text: event.text,
          store: event.store,
          include: event.include,
        }
      : { model: event.model, messages: event.messages, tools: event.tools };
    row.state = 'LLM 응답 대기';
  }
  if (kind === 'llm_response') {
    row.response = {
      output: event.output,
      ...(event.response_status ? { status: event.response_status } : { finish_reason: event.finish_reason }),
    };
    row.state = '응답 수신';
    row.seconds = (event.llm_seconds as number | undefined) ?? elapsed();
    row.turn_usage = event.turn_usage as Json;
  }
  if (kind === 'llm_error') {
    row.response = { error: event.error };
    row.state = '실패';
    row.seconds = (event.llm_seconds as number | undefined) ?? elapsed();
  }
  if (kind === 'tool_selected') {
    row.request = event.arguments;
    row.state = '선택됨';
  }
  if (kind === 'tool_start') row.state = '호출 중';
  if (kind === 'tool_result') {
    row.response = event.result;
    row.seconds = (event.tool_seconds as number | undefined) ?? elapsed();
    row.state = result?.error ? '호출 오류' : result?.valid === false ? '검증 실패' : '완료';
  }
  if (kind === 'validation_feedback') {
    row.response = { ...(row.response as Json | undefined), feedback: event.result };
    row.state = '매핑 수정 필요';
  }
  if (kind === 'step_complete') row.state = '백엔드 채택';

  return {
    ...log,
    order: prior ? log.order : [...log.order, key],
    rows: { ...log.rows, [key]: row },
    selectedKey: log.selectedKey ?? key,
  };
}

/** 생성이 실패하면 — 진행 중이던 행은 실패로 닫는다 */
export function failRows(log: IrLog, message: string, now: number): IrLog {
  const rows = { ...log.rows };
  for (const key of log.order) {
    const row = rows[key]!;
    if (row.seconds === undefined)
      rows[key] = {
        ...row,
        seconds: (now - row.started) / 1000,
        state: '중단 / 실패',
        response: { error: message },
      };
  }
  return { ...log, rows };
}

// ─── 표시 ─────────────────────────────────────────────────────────────────────────────

/** 로그 행의 칸 — 전체 턴 · STEP 내 턴 · STEP · 종류 / 도구 · 상태 · 소요시간 · 토큰 이번 / 누적 · valid */
export function rowCells(row: LogRow, now: number): string[] {
  const time =
    row.seconds !== undefined
      ? row.seconds.toFixed(3) + '초'
      : ((now - row.started) / 1000).toFixed(1) + '초 (진행 중)';
  const tokens =
    row.kind === 'backend'
      ? '—'
      : `${(row.turn_usage?.total_tokens as number | undefined) ?? '—'} / ${(row.usage?.total_tokens as number | undefined) ?? '—'}`;
  const response = row.response as Json | undefined;
  const valid =
    typeof row.valid === 'boolean'
      ? String(row.valid)
      : row.tool === 'validate_mapping'
        ? typeof response?.valid === 'boolean'
          ? String(response.valid)
          : '미판정'
        : '—';
  return [
    String(row.turn ?? '—'),
    String(row.step_turn ?? '—'),
    row.step_id || '—',
    row.tool || 'LLM',
    String(row.state),
    time,
    tokens,
    valid,
  ];
}

/** 진행 줄 — 예산이 있으면 예산 사용량, 없으면 턴 · 토큰 · 경과 */
export function progressText(log: IrLog, started: number, now: number): string {
  const e = log.lastEvent;
  const u = (e.usage as Json) || {};
  const seconds = started ? ((now - started) / 1000).toFixed(1) : '0.0';
  const turn = e.next_turn || e.turn || 0;
  const bu = e.budget_usage as Json | undefined;
  const b = e.budget as IrBudget | undefined;
  if (bu && b) {
    const steps = bu.steps as Record<string, number> | undefined;
    return `STEP ${e.step_id || '준비'} 호출 ${steps?.[e.step_id as string] || 0} (기본 5) · 공통 예비 ${bu.reserve_calls}/2 사용 · LLM ${bu.llm_calls}/${b.limits.llm_calls} · 토큰 ${bu.total_tokens}/${b.limits.tokens} · 시간 ${Number(bu.elapsed_seconds).toFixed(1)}/${b.limits.seconds}초 · 임베딩 ${u.embedding_calls || 0}회`;
  }
  return `전체 ${turn}턴 · 단계 ${e.step_id || '준비'} / ${e.step_turn || 0}턴 · 누적 토큰 ${u.total_tokens || 0} (입력 ${u.input_tokens || 0} / 출력 ${u.output_tokens || 0} / 임베딩 ${u.embedding_tokens || 0}, ${u.embedding_calls || 0}회) · 경과 ${seconds}초`;
}

/** 로그 상세 제목 · 설명 — 고른 행 · 탭(요청 / 응답) */
export function detailOf(row: LogRow | undefined, tab: 'request' | 'response') {
  if (!row)
    return {
      title: '로그 행을 선택하세요',
      meta: '선택한 행의 요청과 응답을 이 영역에서 확인할 수 있습니다.',
      value: { message: '아직 선택된 로그가 없습니다.' } as unknown,
    };
  const value = tab === 'request' ? row.request : row.response;
  return {
    title: `선택한 로그 · ${row.kind === 'backend' ? '백엔드' : row.turn + '턴'} · STEP ${row.step_id} · ${row.tool || 'LLM'}`,
    meta:
      (tab === 'request'
        ? row.kind === 'backend'
          ? '백엔드 처리 입력'
          : row.tool
            ? '도구 호출 인자'
            : 'LLM 프롬프트'
        : '응답 결과') +
      ' · JSON · 2칸 들여쓰기 · ' +
      row.state,
    value:
      value === undefined
        ? {
            status: 'waiting',
            message: tab === 'response' ? '응답을 기다리고 있습니다.' : '요청 정보가 아직 없습니다.',
          }
        : value,
  };
}

export const CHANGE_LABELS: Record<string, string> = {
  replace: '대체',
  unchanged: '동일 · 유지',
  response_binding: '응답 참조',
  input_needed: '입력 필요',
  comparison_unavailable: '비교 불가',
};

/** STEP 대체 파라미터 표 — 파라미터 · Baseline 값 · 적용 값 / 참조 · 처리 */
export function parameterRows(s: StepData): string[][] {
  const bindings = new Map(s.bindings.map((b) => [b.binding_id, b.from]));
  return s.inputs.map((input) => {
    const from = bindings.get(input.ref as string);
    const value =
      input.source === 'bind'
        ? from
          ? `{{${from.from_step_id}.${from.output_name}}}`
          : '연결 미정'
        : ['unresolved', 'run_input'].includes(input.source as string)
          ? '입력 필요'
          : input.value;
    const show = (v: unknown) => (typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? ''));
    return [
      show(input.field || input.parameter_path),
      show(
        input.baseline_present === false
          ? '기준 없음'
          : input.baseline_value === null
            ? 'null'
            : input.baseline_value,
      ),
      show(value),
      [CHANGE_LABELS[input.change_kind as string] || input.change_kind, input.comparison_reason]
        .filter(Boolean)
        .join(' · '),
    ];
  });
}

/** STEP 목록 · 상세의 업무 칸 */
export const taskLabel = (entry: StepEntry) => `업무 ${entry.task_sequence ?? '—'} · STEP ${entry.id}`;
