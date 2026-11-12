// 시나리오 등록 — 화면이 보여 줄 것을 계산하는 순수 함수 (지금 web/scenario-register.js 와 같은 규칙).
import type { Schemas } from '../../api/client';
import { irStepsById, type Ir, type IrStep } from '../../api/ir';
import type { StepState } from '../../components/Stepper';
import { apiCode, clean } from '../../lib/format';

export type AnalyzeResult = Schemas['AnalyzeResult'];
export type Row = Schemas['StepSelection'];
export type Gate = Schemas['Gate'];
export type StepMap = Schemas['StepMap'];
export type RegisteredRecord = Schemas['RegisteredRecord'];

export const STAGES = [
  ['intent', '요청 이해'],
  ['paths', '경로 찾기'],
  ['apis', 'API 고르기'],
  ['ir', '시나리오 생성'],
] as const;
export type StageKey = (typeof STAGES)[number][0];
export const LIVE: StageKey[] = ['intent', 'paths', 'apis'];

/** 미리보기가 읽는 모양 — 지금 분석한 것 또는 등록 기록 */
export interface View {
  result: Pick<AnalyzeResult, 'tasks' | 'paths' | 'apis' | 'gate'>;
  stepMap: StepMap[];
  irSteps: Record<string, IrStep>;
  ir: Ir | null;
  irError: string | null;
  /** 시나리오 생성 중 (입력값 자리에 '만드는 중') */
  irRunning: boolean;
  saved: RegisteredRecord | null;
}

export const keyOf = (r: { path_sequence: number | null; step: number | null }) =>
  `${r.path_sequence}-${r.step}`;

/** 고른 API 의 한글 이름 (후보 목록에서) */
export function apiName(row: Row): string {
  const c = row.api_candidates.find((x) => row.selected && x.api_id === row.selected.api_id);
  return c?.name ?? '';
}

export const apiLabel = (row: Row) => (row.selected ? apiName(row) || apiCode(row.selected.api_id) : '-');

export function irStepOf(v: View, row: Row): IrStep | null {
  const m = v.stepMap.find((s) => s.source_step === keyOf(row));
  return m ? (v.irSteps[m.step_id] ?? null) : null;
}

/** 단계 번호 = 업무 안에서 몇 번째 (IR 단계 번호와 같다) */
export function ordinal(result: View['result'], key: string): { row: Row | null; label: string } {
  const rows = result.apis.api_selection_results;
  const row = rows.find((x) => keyOf(x) === key);
  if (!row) return { row: null, label: key };
  const n =
    rows
      .filter((x) => x.path_sequence === row.path_sequence)
      .sort((a, b) => a.step - b.step)
      .indexOf(row) + 1;
  return { row, label: `업무 ${row.path_sequence} · 단계 ${n}` };
}

export interface ConfirmItem {
  key: string;
  label: string;
  head: string;
  why: string[];
}

/** 확인할 것 — 사람이 확인하지 않은 API 선택(가선택 · LLM 이 고른 API). 단계마다 체크해야 등록된다 */
export function toConfirm(result: View['result']): ConfirmItem[] {
  return result.gate.need_steps.map((key) => {
    const { row, label } = ordinal(result, key);
    const why = result.apis.unresolved.filter((u) => keyOf(u) === key).map((u) => clean(u.reason));
    return { key, label, head: `${row ? row.edge : key} — ${row ? apiLabel(row) : '-'}`, why };
  });
}

export interface Memo {
  text: string;
  where: string;
}

/** 메모 — ①② 미해결 · IR 이 남긴 질문 (접어서 보여 주기만) */
export function memos(v: View): Memo[] {
  const out: Memo[] = [];
  const seen = new Set<string>();
  const loose: unknown[] = [...v.result.tasks.unresolved, ...(v.result.paths?.unresolved ?? [])];
  loose.forEach((u) => {
    const text = clean(typeof u === 'string' ? u : ((u as { reason?: string })?.reason ?? ''));
    if (text && !seen.has(text)) {
      seen.add(text);
      out.push({ text, where: '' });
    }
  });
  (v.ir?.unresolved ?? [])
    .filter((u) => u.status === 'open')
    .forEach((u) =>
      out.push({
        text: clean(u.reason),
        where: (u.step_ids ?? []).map((s) => `업무 ${s.split('-')[0]} · 단계 ${s.split('-')[1]}`).join(', '),
      }),
    );
  return out;
}

/** 시나리오를 만들 수 있는 분석 결과인가 — 차단 · 실행할 것 없음이면 멈춤 */
export const canBuild = (result: AnalyzeResult | null) =>
  Boolean(result) && !['차단', '실행할 것 없음'].includes(result!.gate.status);

/** 등록 기록 → 미리보기 모양 */
export function viewFromRecord(rec: RegisteredRecord): View {
  const ir = rec.ir as Ir;
  return {
    result: { tasks: rec.tasks, apis: rec.selection, gate: rec.gate, paths: rec.paths },
    stepMap: rec.step_map,
    irSteps: irStepsById(ir),
    ir,
    irError: null,
    irRunning: false,
    saved: rec,
  };
}

/** 분석이 단계 k 를 시작했을 때 진행 표시 — 앞은 완료, k 는 진행 중, 뒤는 대기 */
export function stagesAt(k: StageKey): Partial<Record<StageKey, StepState>> {
  const at = LIVE.indexOf(k);
  return Object.fromEntries(LIVE.map((x, i) => [x, i < at ? 'done' : i === at ? 'now' : 'wait']));
}
