// 테스트 견본 (2026-11-13)
// - inspect.json: 가짜 LLM 서버의 분석 결과(트레이스 포함) · 승인 응답 · 승인본 목록 · 예산
// - ir-log-stream.json · ir-log-failed.json: 실제 IR 생성 로그(성공 · 실패)를 인증값을 가리고 프롬프트 본문을 줄인 것
// - ir-runs.json: 누적 실행 기록 요약 3줄 (완료 · 실패 · KB 검색 옵션)
import type { Schemas } from '../../../api/client';
import failed from './ir-log-failed.json';
import runs from './ir-runs.json';
import data from './inspect.json';
import stream from './ir-log-stream.json';

const clone = <T>(x: T): T => structuredClone(x);

export const analyzeResult = () => clone(data.analyze) as unknown as Schemas['AnalyzeResult'];
export const approveResult = () => clone(data.approve) as unknown as Schemas['ApproveResult'];
export const approvedList = () => clone(data.approved) as unknown as Schemas['ApprovedList'];
export const budget = () => clone(data.budget) as unknown as Schemas['BudgetResult'];
export const irEvents = () => clone(stream) as unknown as Record<string, unknown>[];
export const irFailedEvents = () => clone(failed) as unknown as Record<string, unknown>[];
export const irRuns = () => clone(runs) as unknown as Schemas['IrRunList'];
export const toLines = (events: Record<string, unknown>[]) => events.map((e) => JSON.stringify(e) + '\n');

/** 서버가 스트림으로 보내는 모양 — 저널의 generation_complete 와 같다 */
export const APPROVED_FILE = () => approveResult().ir_handoff.filename!;

/** 단계를 직접 확인해야 승인되는 결과 — 2번째 단계(1-1) */
export function withStepCheck(): Schemas['AnalyzeResult'] {
  const r = analyzeResult();
  r.gate.need_steps = ['1-1'];
  r.gate.steps.find((s) => s.key === '1-1')!.requirement = '단계 승인';
  return r;
}
