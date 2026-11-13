// 상태 그래프 편집기 — 그래프마다 그리던 내용 (그래프를 바꾸거나 다른 메뉴로 가도 유지, 새로고침 전까지 — 예전 화면의 MEM)
import { createStore } from '../../../lib/store';
import type { GraphEntry, GState, Sel } from './editorModel';

export interface EditorState {
  byGraph: Record<string, GState>;
  /** 지금 보는 그래프 id */
  current: string | null;
  /** 이 화면에서 새로 만든 그래프 (저장 전) */
  created: GraphEntry[];
  sel: Sel;
  creating: boolean;
  newG: { cg: string; name: string; entity: string } | null;
  menu: boolean;
  allTodo: boolean;
  modal: null | 'test' | 'save' | 'settings';
  filter: string;
  test: Record<string, { from: string; target: string; must: string }>;
}

export const editor = createStore<EditorState>(() => ({
  byGraph: {},
  current: null,
  created: [],
  sel: { kind: 'none' },
  creating: false,
  newG: null,
  menu: false,
  allTodo: false,
  modal: null,
  filter: '',
  test: {},
}));

/** 지금 그래프의 상태를 고친다 */
export function setGraph(gid: string, change: (s: GState) => GState) {
  editor.set((e) => ({ byGraph: { ...e.byGraph, [gid]: change(e.byGraph[gid]!) } }));
}
