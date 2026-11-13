import { describe, expect, it } from 'vitest';

import { admin } from '../fixtures';
import {
  freeGroups,
  freeSpot,
  graphList,
  guessField,
  initial,
  issues,
  nameOf,
  search,
  toYaml,
  view,
  type Data,
  type GraphFile,
} from './editorModel';

// 기대값의 바탕: 예전 편집기(web/graph-editor.js)와 같은 그래프로 저장 YAML 이 글자까지 같은지 대조했다 (2026-11-13)
const d = admin();
const D = {
  graphs: d.graphs.graphs,
  drafts: d.graphs.drafts,
  codes: d.codes.codes,
  ops: d.operations.ops,
} as unknown as Data;
const ord = () => graphList(D).find((g) => g.id === 'ORD_STAT_GBCD')!;

describe('상태 그래프 편집 규칙', () => {
  it('손으로 쓴 그래프는 공통코드 순서로 한 줄에 6개씩 자동 배치', () => {
    const s = initial(ord(), D.ops);
    expect(s.nodes).toEqual({
      '25': { x: 110, y: 150, role: 'api' },
      '30': { x: 290, y: 150, role: 'api' },
      '45': { x: 470, y: 150, role: 'api' },
      '50': { x: 650, y: 150, role: 'api' },
    });
    expect(s.stateField).toEqual({ v: 'lastDlvstPrgrGbcd', st: '확정' });
    expect(s.saved).toBeNull();
  });

  it('화면에서 저장한 그래프 — 배치 · 승인본 번호, 서버 파일에 없는 칸(external_transitions)이 있어도 연다', () => {
    const g0 = d.graphs.graphs.find((g) => g.graph.id === 'ORD_STAT_GBCD')!;
    const draft = {
      ...structuredClone(g0),
      version: 2,
      layout: { '25': [100, 200], '30': [300, 200] },
    } as unknown as GraphFile;
    delete (draft as Partial<GraphFile>).external_transitions;
    const g = graphList({ ...D, drafts: [draft] }).find((x) => x.id === 'ORD_STAT_GBCD')!;
    const s = initial(g, D.ops);
    expect(s.saved).toEqual({ v: 2 });
    expect(Object.keys(s.nodes)).toEqual(['25', '30']);
    expect(s.edges).toHaveLength(6);
  });

  it('저장 YAML — 이름 있는 화살표만, 이름 없는 것은 수만 머리에', () => {
    const g = ord();
    const s = initial(g, D.ops);
    s.nodes['10'] = { x: 85, y: 420, role: 'api' };
    s.edges.push({ from: '10', to: '25', name: '', st: '확정', origin: '사람' });
    const y = toYaml(g, { ...s, saved: { v: 1 } }, view(g, s, D.codes));
    expect(y.split('\n')[0]).toBe(
      '# 주문상태 그래프 — 화면에서 저장 (승인본 v1). 노드 흐름만: 상태 · 화살표 · 업무 이름 (이름 없는 화살표 1개는 빠짐)',
    );
    expect(y).toContain('\nversion: 1\n');
    expect(y).not.toContain('from: "10"');
    expect(y.split('\nlayout:')[1]).toMatch(
      /^ {3}# 화면 배치\n {2}"10": \[85, 420\]\n {2}"25": \[110, 150\]/,
    );
  });

  it('다음 할 일 — 이름 없는 화살표는 필수, 되돌리는 화살표가 없으면 확인', () => {
    const g = ord();
    const s = initial(g, D.ops);
    s.edges = s.edges.filter((e) => e.name !== '배송완료취소');
    s.edges.push({ from: '50', to: '45', name: '', st: '확정', origin: '사람' });
    const list = issues(s, view(g, s, D.codes));
    expect(list.map((x) => x.lv)).toEqual(['warn', 'err']);
    expect(list[1]!.msg).toBe('배송완료 → 출고: 이 변화를 업무에서 뭐라고 부르는지 적으세요.');
  });

  it('시험해 보기 — 이름 있는 화살표로, 거쳐야 할 상태를 지나서', () => {
    const g = ord();
    const s = initial(g, D.ops);
    const v = view(g, s, D.codes);
    expect(search(v, '25', '50', null)!.map((e) => e.name)).toEqual(['출고진행', '출고완료', '배송완료']);
    expect(search(v, '30', '30', '25')!.map((e) => e.name)).toEqual(['출고취소', '출고진행']);
    expect(search(v, '25', '10', null)).toBeNull();
  });

  it('빈 자리 · 새 그래프(아직 그래프로 안 만든 공통코드 그룹) · 상태 필드 추정', () => {
    expect(freeSpot({})).toEqual({ x: 85, y: 150 });
    expect(freeSpot({ a: { x: 85, y: 150, role: 'api' } })).toEqual({ x: 235, y: 150 });
    const free = freeGroups(graphList(D), D.codes);
    expect(free.map((c) => c.id)).toEqual(['ITEM_SELL_GBCD']);
    expect(nameOf(free[0]!)).toBe(free[0]!.name.replace(/(구분)?코드$/, ''));
    expect(guessField({ graph: { state_field: 'x' } }, D.ops)).toEqual({ v: 'x', why: '그래프에 적힌 값' });
  });
});
