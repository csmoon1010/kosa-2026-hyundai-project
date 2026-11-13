// 상태 그래프 편집기 — 데이터 · 저장소를 묶어 동작을 준다 (예전 web/graph-editor.js 의 addNode · addEdge · removeNode · next · 저장 …)
import { useEffect } from 'react';

import { put } from '../../../api/client';
import { useCodes, useGraphs, useOperations, useRefreshAdmin } from '../../../api/queries';
import { useStore } from '../../../lib/store';
import {
  clampNode,
  freeSpot,
  graphList,
  initial,
  key,
  newGraph,
  snap,
  toYaml,
  view,
  type Data,
  type GraphEntry,
  type GState,
  type Sel,
} from './editorModel';
import { editor, setGraph } from './editorStore';

export function useGraphEditor(dom: string, toast: (msg: string) => void) {
  const graphsQ = useGraphs();
  const codesQ = useCodes();
  const opsQ = useOperations();
  const refreshAdmin = useRefreshAdmin();
  const e = useStore(editor);

  const ready = Boolean(graphsQ.data && codesQ.data && opsQ.data);
  const D: Data | null = ready
    ? {
        graphs: graphsQ.data!.graphs,
        drafts: graphsQ.data!.drafts,
        codes: codesQ.data!.codes,
        ops: opsQ.data!.ops,
      }
    : null;
  const all = D ? graphList(D, e.created) : [];
  const mine = all.filter((g) => g.dom === dom);
  // 이 도메인의 그래프가 아니면 첫 그래프로 (도메인 탭을 바꿀 때 — 그리던 내용은 그래프마다 남는다)
  const g: GraphEntry | undefined = mine.find((x) => x.id === e.current) ?? mine[0];

  useEffect(() => {
    if (!D || !g) return;
    if (e.current !== g.id || !e.byGraph[g.id])
      editor.set((st) => ({
        current: g.id,
        sel: st.current === g.id ? st.sel : { kind: 'none' },
        byGraph: st.byGraph[g.id] ? st.byGraph : { ...st.byGraph, [g.id]: initial(g, D.ops) },
      }));
  });

  const s: GState | undefined = g ? e.byGraph[g.id] : undefined;
  const v = g && s && D ? view(g, s, D.codes) : null;

  if (!D || !g || !s || !v)
    return { ready, D, all, mine, g: undefined, s: undefined, v: undefined, e } as const;

  const gid = g.id;
  const select = (sel: Sel) => editor.set({ sel });
  const refreshState = (change: (st: GState) => GState) => setGraph(gid, change);

  const actions = {
    select,
    switchTo: (id: string) =>
      editor.set({ current: id, sel: { kind: 'none' }, creating: false, menu: false }),
    /** 공통코드를 캔버스에 — 놓은 자리 (없으면 빈 자리) */
    addNode(c: string, p?: { x: number; y: number }) {
      if (s.nodes[c]) return select({ kind: 'node', id: c });
      const at = p ? clampNode({ x: snap(p.x), y: snap(p.y) }) : freeSpot(s.nodes);
      refreshState((st) => ({ ...st, nodes: { ...st.nodes, [c]: { ...clampNode(at), role: 'api' } } }));
      select({ kind: 'node', id: c });
      toast(
        p
          ? `${v.sn(c)} 을(를) 놓았습니다.`
          : `${v.sn(c)} 을(를) 빈 자리에 놓았습니다. 끌어서 옮길 수 있어요.`,
      );
    },
    /** 끌어서 옮기는 중 · 놓았을 때 (놓으면 5 단위로 맞춘다) */
    moveNode(c: string, p: { x: number; y: number }, done: boolean) {
      const at = clampNode(done ? { x: snap(p.x), y: snap(p.y) } : p);
      refreshState((st) => ({
        ...st,
        nodes: { ...st.nodes, [c]: { ...st.nodes[c]!, ...(done ? clampNode(at) : at) } },
      }));
    },
    addEdge(a: string, b: string) {
      if (a === b) return;
      const k = key(a, b);
      if (v.edgeOf(k)) {
        select({ kind: 'edge', id: k });
        return toast('이미 있는 화살표라 그 화살표를 열었습니다.');
      }
      refreshState((st) => ({
        ...st,
        edges: [...st.edges, { from: a, to: b, name: '', st: '확정', origin: '사람' }],
      }));
      select({ kind: 'edge', id: k });
      toast(
        s.nodes[a]?.role === 'ext'
          ? '외부에서 생기는 상태에서 나온 화살표라 API 가 필요 없습니다.'
          : `${v.NAME(a)} → ${v.NAME(b)} 화살표를 만들었습니다. 업무에서 부르는 이름을 적으세요.`,
      );
    },
    removeNode(c: string) {
      const n = s.edges.filter((x) => x.from === c || x.to === c).length;
      refreshState((st) => {
        const nodes = { ...st.nodes };
        delete nodes[c];
        return { ...st, nodes, edges: st.edges.filter((x) => x.from !== c && x.to !== c) };
      });
      select({ kind: 'none' });
      toast(`${v.sn(c)} 을(를) 캔버스에서 뺐습니다${n ? ` (화살표 ${n}개 함께)` : ''}.`);
    },
    /** 화살표 지우기 — Delete 키(how='key') · 패널 버튼('button') · 바깥 화살표('silent') */
    removeEdge(k: string, how: 'key' | 'button' | 'silent' = 'key') {
      const ed = v.edgeOf(k);
      if (!ed) return;
      refreshState((st) => ({ ...st, edges: st.edges.filter((x) => key(x.from, x.to) !== k) }));
      select({ kind: 'none' });
      if (how === 'key') toast(`${v.NAME(ed.from)} → ${v.NAME(ed.to)} 화살표를 지웠습니다.`);
      if (how === 'button') toast('화살표를 지웠습니다.');
    },
    /** 화살표 이름 확정 → 다음 이름 없는 화살표로 */
    nameEdge(k: string, name: string) {
      const value = name.trim();
      if (!value) return toast('업무에서 부르는 이름을 적으세요.');
      let edges = s.edges.map((x) =>
        key(x.from, x.to) === k ? { ...x, name: value, st: '확정', origin: '사람' } : x,
      );
      refreshState((st) => ({ ...st, edges }));
      edges = edges.filter((x) => !(s.nodes[x.from]?.role === 'ext'));
      const n = edges.find((x) => !x.name);
      select(n ? { kind: 'edge', id: key(n.from, n.to) } : { kind: 'none' });
      toast(`'${value}' 로 확정했습니다.`);
    },
    /** 이름 없는 화살표로 차례로 */
    nextUnnamed() {
      const list = v.workEdges().filter((x) => !x.name);
      if (!list.length) return;
      const cur = list.findIndex((x) => e.sel.kind === 'edge' && e.sel.id === key(x.from, x.to));
      const n = list[(cur + 1) % list.length]!;
      select({ kind: 'edge', id: key(n.from, n.to) });
    },
    /** 저장본 · 확인된 그래프로 되돌리기 (없으면 캔버스 비우기) */
    reset() {
      refreshState(() => initial(g, D.ops));
      select({ kind: 'none' });
      toast(
        g.draft
          ? '저장본으로 되돌렸습니다.'
          : g.k.transitions.length
            ? '확인된 그래프로 되돌렸습니다.'
            : '캔버스를 비웠습니다.',
      );
    },
    setField(f: string) {
      refreshState((st) => ({ ...st, stateField: { v: f, st: '추정' } }));
    },
    confirmField() {
      refreshState((st) => ({ ...st, stateField: { ...st.stateField, st: '확정' } }));
      toast('상태 필드를 확정했습니다.');
    },
    /** 확인 후 저장 — 승인본 번호를 올리고 서버에 (data/graphs/<id>.yaml 에 합침) */
    async save() {
      const next = { ...s, saved: { v: (s.saved ? s.saved.v : 0) + 1 } };
      refreshState(() => next);
      let where: string;
      try {
        const j = await put<{ file?: string }>('/api/admin/graphs/' + encodeURIComponent(gid), {
          yaml: toYaml(g, next, view(g, next, D.codes)),
        });
        where = j.file ? ` · ${j.file}` : '';
        await refreshAdmin();
      } catch (err) {
        where = ` · 저장 실패: ${(err as Error).message}`;
      }
      editor.set({ modal: null });
      toast(`승인본 v${next.saved.v} 로 저장했습니다${where}`);
    },
  };
  return { ready, D, all, mine, g, s, v, e, ...actions } as const;
}

/** 새 그래프 만들기 — 아직 그래프로 안 만든 공통코드 그룹으로 빈 캔버스 */
export function createGraph(
  D: Data,
  dom: string,
  cgId: string,
  name: string,
  entity: string,
  toast: (m: string) => void,
) {
  const cg = D.codes.find((x) => x.id === cgId);
  if (!cg) return toast('공통코드 그룹을 고르세요.');
  if (!name.trim()) return toast('그래프 이름을 적으세요.');
  const g = newGraph(cg, name.trim(), dom, entity, D.ops);
  editor.set((st) => ({
    created: [...st.created, g],
    current: g.id,
    byGraph: { ...st.byGraph, [g.id]: initial(g, D.ops) },
    creating: false,
    newG: null,
    sel: { kind: 'none' },
  }));
  toast(`${g.name} 그래프를 만들었습니다. 왼쪽 공통코드를 캔버스로 끌어다 놓으세요.`);
}
