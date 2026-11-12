// 테스트 견본 — 가짜 LLM 서버로 등록 → 2회 반복 드라이런한 실제 응답 (2026-11-12).
import type { Schemas } from '../../../api/client';
import data from './dry-run.json';

const clone = <T>(x: T): T => structuredClone(x);

export const scenarios = () => clone(data.scenarios) as unknown as Schemas['RegisteredSummary'][];
export const dryRunResult = () => clone(data.run) as unknown as Schemas['Run'];
export const runs = () => clone(data.runs) as unknown as Schemas['Run'][];

/** 되돌릴 수 없는 단계(1-1)가 있어 실행할 때마다 확인해야 하는 시나리오 */
export function withR2(): Schemas['RegisteredSummary'][] {
  const list = scenarios();
  list[0]!.irreversible = 1;
  list[0]!.confirm_steps = [{ key: '1-1', edge: '배송완료취소' }];
  return list;
}
