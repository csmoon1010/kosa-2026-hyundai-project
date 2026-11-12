import { describe, expect, it } from 'vitest';

import { irEvents, irFailedEvents } from '../fixtures';
import {
  applyEvent,
  detailOf,
  emptyLog,
  failRows,
  parameterRows,
  progressText,
  rowCells,
  taskLabel,
  updateSteps,
  type IrLog,
} from './irLog';

// 기대값은 예전 화면(web/scenario-ir-draft.js)에 같은 이벤트를 흘려 넣어 얻은 표와 대조해 확인한 값 (2026-11-13)
const run = (events: Record<string, unknown>[]) => {
  let log: IrLog = emptyLog();
  for (const e of events) {
    const r = e.result as Record<string, unknown> | undefined;
    log = applyEvent(
      log,
      e.event === 'generation_complete'
        ? { event: e.event, file: r?.file, usage: r?.usage, log_file: r?.log_file }
        : e,
      0,
    );
  }
  return log;
};
const steps = (log: IrLog) => log.steps.map((id) => [taskLabel(log.entries[id]!), log.entries[id]!.status]);

describe('IR 생성 진행 → 로그 행 · STEP (혜정 IR 영역)', () => {
  it('성공한 생성 — 로그 30행, 첫 행이 먼저 골라진다, STEP 2개', () => {
    const log = run(irEvents());
    expect(log.order).toHaveLength(30);
    expect(log.order.slice(0, 4).map((k) => rowCells(log.rows[k]!, 0))).toEqual([
      ['—', '—', '1-1', 'Canonical · 백엔드', '완료', '0.000초', '—', '—'],
      ['1', '1', '1-1', 'LLM', '응답 수신', '1.968초', '3995 / 3995', '—'],
      ['1', '1', '1-1', 'LLM 통신 시도 1 · 백엔드', '완료', '1.964초', '—', '—'],
      ['1', '1', '1-1', 'get_parameter_knowledge', '완료', '0.013초', '— / 3995', '—'],
    ]);
    expect(log.selectedKey).toBe(log.order[0]);
    expect(steps(log)).toEqual([
      ['업무 1 · STEP 1-1', '초안 완료 · 확인 필요'],
      ['업무 1 · STEP 1-2', '초안 완료'],
    ]);
    expect(log.modeStatus).toBe('실행 옵션: 중지조건·재시도');
    expect(log.logFile?.log_file).toMatch(/IRRUN-.*\.jsonl$/);
  });

  it('검증 실패 행 · 매핑 수정 요청이 표시된다', () => {
    const log = run(irEvents());
    const states = log.order.map((k) => log.rows[k]!.state);
    expect(states).toContain('검사 / 통신 오류');
    expect(states).toContain('수정 요청');
    expect(log.order.map((k) => rowCells(log.rows[k]!, 0)[7])).toContain('false');
  });

  it('진행 줄 — 예산이 있으면 예산 사용량', () => {
    const log = run(irEvents());
    expect(progressText(log, 1, 1)).toMatch(
      /^STEP 1-2 호출 \d+ \(기본 5\) · 공통 예비 0\/2 사용 · LLM \d+\/12 · 토큰 \d+\/130000 · 시간 [\d.]+\/150초/,
    );
    expect(progressText(emptyLog(), 1000, 3500)).toBe(
      '전체 0턴 · 단계 준비 / 0턴 · 누적 토큰 0 (입력 0 / 출력 0 / 임베딩 0, 0회) · 경과 2.5초',
    );
  });

  it('행 상세 — 요청은 LLM 프롬프트, 응답 없으면 기다리는 중', () => {
    const log = run(irEvents());
    const llm = log.rows[log.order[1]!]!;
    expect(detailOf(llm, 'request').title).toBe('선택한 로그 · 1턴 · STEP 1-1 · LLM');
    expect(detailOf(llm, 'request').meta).toBe('LLM 프롬프트 · JSON · 2칸 들여쓰기 · 응답 수신');
    expect(detailOf(undefined, 'response').title).toBe('로그 행을 선택하세요');
    expect(detailOf({ key: 'x', started: 0, state: '호출 중', tool: 't' }, 'response').value).toEqual({
      status: 'waiting',
      message: '응답을 기다리고 있습니다.',
    });
  });

  it('대체 파라미터 표 — Baseline 비교 결과', () => {
    const log = run(irEvents());
    const rows = parameterRows(log.entries['1-2']!.s);
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.every((r) => r.length === 4)).toBe(true);
    expect(rows.some((r) => r[2]!.startsWith('{{1-1.'))).toBe(true); // 앞 STEP 응답 참조
  });

  it('실패한 생성 — 진행 중이던 STEP 은 생성 실패, 열린 행은 중단 / 실패로 닫힌다', () => {
    let log = run(irFailedEvents());
    log = failRows(updateSteps(log, { event: 'generation_error' }), '정지', 5000);
    expect(log.order).toHaveLength(15);
    expect(steps(log)).toEqual([
      ['업무 1 · STEP 1-1', '생성 실패'],
      ['업무 1 · STEP 1-2', '대기'],
    ]);
    expect(log.order.every((k) => log.rows[k]!.seconds !== undefined)).toBe(true);
  });
});
