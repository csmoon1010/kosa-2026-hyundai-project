// Scenario IR (혜정 IR 생성 결과) — 서버 모델에서는 자유 형식(dict)이라 화면이 읽는 칸만 적는다.
// 형식의 기준은 docs/scenario-ir.md · tap/ir/draft_build.py. 칸을 더 읽게 되면 여기에 더한다.

export interface IrInput {
  field: string;
  /** fixed 값 · bind 앞 단계 결과 · unresolved 정해지지 않음 */
  source: string;
  value?: unknown;
  ref?: string | null;
}

/** IR 모양({binding_id, from:{…}}) · 실행 이력 모양({binding_id, from_step_id, output_name}) 둘 다 */
export interface IrBinding {
  binding_id: string;
  from?: { from_step_id?: string; output_name?: string };
  from_step_id?: string;
  output_name?: string;
}

export interface IrStep {
  step_id: string;
  inputs?: IrInput[];
  bindings?: IrBinding[];
}

export interface IrUnresolved {
  status?: string;
  reason?: string;
  step_ids?: string[];
}

export interface Ir {
  scenario_id?: string;
  tasks?: { steps?: IrStep[] }[];
  unresolved?: IrUnresolved[];
}

/** 시나리오 생성 스트림(POST /api/register/ir)에서 화면이 쓰는 줄 */
export type IrEvent =
  | { event: 'review_draft'; filename: string | null; steps?: { step_id: string; source_step: string }[] }
  | { event: 'scenario_steps'; steps?: unknown[] }
  | { event: 'step_preview'; step_id: string; step?: IrStep }
  | { event: 'generation_complete'; result: { ir: Ir; file?: string | null } }
  | { event: 'generation_error'; error?: string }
  | { event: string; [key: string]: unknown };

export const irStepsById = (ir: Ir | null | undefined): Record<string, IrStep> =>
  Object.fromEntries((ir?.tasks ?? []).flatMap((t) => t.steps ?? []).map((s) => [s.step_id, s]));
