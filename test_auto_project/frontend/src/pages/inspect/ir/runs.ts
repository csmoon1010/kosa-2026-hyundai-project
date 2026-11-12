// 누적 IR 실행 기록 — 쿼리 키 · 한 줄의 칸 (예전 화면의 표 그대로)
import type { Schemas } from '../../../api/client';
import { describeOptions } from './irLog';

export const irRunsKey = ['inspect', 'ir', 'runs'] as const;
type Run = Schemas['IrRunSummary'];

export const RUN_HEADINGS = [
  '실행 시각',
  '생성 옵션',
  '상태',
  '수행 시간',
  'LLM 호출',
  '턴',
  '입력 토큰',
  '출력 토큰',
  '임베딩 토큰',
  '총 토큰',
  'STEP 수',
  'STEP 최대 호출',
  '임베딩 호출',
  '예비 사용',
  '중단 사유',
  '로그',
];

/** 누적 IR 실행 기록 한 줄의 칸 (예전 화면의 표 그대로) */
export function runCells(run: Run): string[] {
  const b = run.budget;
  const bu = run.budget_usage;
  const l = b?.limits;
  const ratio = (value: unknown, limit: unknown) => `${String(value ?? 0)} / ${limit ?? '—'}`;
  const steps = bu?.steps ?? {};
  const reserve =
    b?.version === 'step_budget_v1' && l
      ? `호출 ${bu?.reserve_calls || 0}/2 · 토큰 ${bu?.token_reserve_used || 0}/${Math.min(30000, Math.max(0, l.tokens - b.step_count * 50000))} · 시간 ${Number(bu?.time_reserve_used || 0).toFixed(1)}/${Math.min(30, Math.max(0, l.seconds - b.step_count * 60))}초`
      : '—';
  return [
    run.started_at ? new Date(run.started_at).toLocaleString('ko-KR') : '—',
    run.options ? describeOptions(run.options) : '기록 없음',
    run.status || '미완료',
    ratio(run.duration_seconds, l?.seconds) + '초',
    ratio(run.model_calls, l?.llm_calls),
    String(run.turns ?? 0),
    String(run.input_tokens ?? 0),
    String(run.output_tokens ?? 0),
    String(run.embedding_tokens ?? 0),
    ratio(run.total_tokens, l?.tokens),
    String(run.step_count ?? '—'),
    Object.keys(steps).length ? `${Math.max(0, ...Object.values(steps))} (기본 5)` : '—',
    String(run.embedding_calls ?? '—'),
    reserve,
    run.budget_reason || '—',
  ];
}
