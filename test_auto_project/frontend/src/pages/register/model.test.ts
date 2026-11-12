import { describe, expect, it } from 'vitest';

import { analyzeResult, record, withConfirm } from './fixtures';
import { canBuild, memos, ordinal, stagesAt, toConfirm, viewFromRecord, type View } from './model';

const view = (patch: Partial<View> = {}): View => ({
  result: analyzeResult(),
  stepMap: [],
  irSteps: {},
  ir: null,
  irError: null,
  irRunning: false,
  saved: null,
  ...patch,
});

describe('시나리오 등록 규칙 (scenario-register.js 와 같게)', () => {
  it('단계 번호는 업무 안에서 몇 번째', () => {
    expect(ordinal(analyzeResult(), '1-1').label).toBe('업무 1 · 단계 2');
    expect(ordinal(analyzeResult(), '9-9')).toEqual({ row: null, label: '9-9' });
  });

  it('확인할 것 = 사람이 확인하지 않은 API 선택, 이유는 오류 이름 · 코드를 뗀 문구', () => {
    expect(toConfirm(analyzeResult())).toEqual([]);
    expect(toConfirm(withConfirm())).toEqual([
      {
        key: '1-1',
        label: '업무 1 · 단계 2',
        head: '배송완료취소 — 출고취소처리',
        why: ['LLM 이 고른 API — 확인 필요'],
      },
    ]);
  });

  it('메모 — ①② 미해결은 겹치면 한 번, IR 이 남긴 질문은 단계 위치와 함께 (열린 것만)', () => {
    const r = analyzeResult();
    r.tasks.unresolved = ['GoalError: 건수가 애매합니다'];
    r.paths.unresolved = ['건수가 애매합니다'];
    const ir = {
      unresolved: [
        { status: 'open', reason: '협력사코드 확인', step_ids: ['1-2'] },
        { status: 'resolved', reason: '끝난 것', step_ids: ['1-1'] },
      ],
    };
    expect(memos(view({ result: r, ir }))).toEqual([
      { text: '건수가 애매합니다', where: '' },
      { text: '협력사코드 확인', where: '업무 1 · 단계 2' },
    ]);
  });

  it('차단 · 실행할 것 없음이면 시나리오를 만들지 않는다', () => {
    const r = analyzeResult();
    expect(canBuild(r)).toBe(true);
    r.gate.status = '차단';
    expect(canBuild(r)).toBe(false);
    expect(canBuild(null)).toBe(false);
  });

  it('진행 표시 — 앞은 완료, 지금은 진행 중, 뒤는 대기', () => {
    expect(stagesAt('paths')).toEqual({ intent: 'done', paths: 'now', apis: 'wait' });
  });

  it('등록 기록 → 미리보기 모양 (IR 단계를 번호로)', () => {
    const v = viewFromRecord(record());
    expect(Object.keys(v.irSteps)).toEqual(['1-1', '1-2']);
    expect(v.stepMap).toEqual([
      { step_id: '1-1', source_step: '1-0' },
      { step_id: '1-2', source_step: '1-1' },
    ]);
    expect(v.saved?.name).toBe('배송완료 취소');
  });
});
