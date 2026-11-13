// 상태 그래프 만들기 — 편집 규칙 (web/graph-editor.js 의 guessField · initial · CODES · issues · search · yaml … 를 그대로).
// 업무 담당자는 상태 · 화살표 · 업무 이름만 정한다 (노드 흐름). API 와 '조회로 찾을 수 있는 상태'는 이 화면에서 다루지 않는다 —
// 시나리오를 만들 때 ② 경로 탐색 · ③ API 선택이 API Metadata 에서 정하고 승인본에 고정한다.
import type { Schemas } from '../../../api/client';

export type GraphFile = Schemas['GraphFile'];
type CodeTable = Schemas['CodeTable'];
type Op = Schemas['OperationDigest'];

/** 캔버스 크기 · 상태 상자 크기 (좌표는 상자 가운데) */
export const VB = { w: 1100, h: 560 };
export const NW = 124;
export const NH = 52;
export const DOMS: Record<string, string> = { pd: '상품', od: '주문', ds: '물류' };

export const key = (a: string, b: string) => `${a}>${b}`;
export const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
export const snap = (v: number) => Math.round(v / 5) * 5;

export interface GraphEntry {
  id: string;
  name: string;
  dom: string;
  k: GraphFile;
  /** 화면에서 저장한 적이 있으면 그 저장본 (배치 · 승인본 번호) */
  draft?: GraphFile;
  isNew?: boolean;
}

export interface ENode {
  x: number;
  y: number;
  role: 'api' | 'entry' | 'ext';
}
export interface EEdge {
  from: string;
  to: string;
  name: string;
  st: string;
  origin: string;
}
export interface GState {
  graph: string;
  nodes: Record<string, ENode>;
  edges: EEdge[];
  stateField: { v: string | null; st: '추정' | '확정' };
  saved: { v: number } | null;
}

export interface Data {
  graphs: GraphFile[];
  drafts: GraphFile[];
  codes: CodeTable[];
  ops: Op[];
}

/** 서버 응답은 다시 검사하지 않으므로 그래프 파일에 없는 칸을 채운다 (화면에서 저장한 파일엔 external_transitions 가 없다) */
export const normalizeGraph = (k: GraphFile): GraphFile => ({
  ...k,
  transitions: k.transitions ?? [],
  external_transitions: k.external_transitions ?? [],
  graph: {
    ...k.graph,
    entry_states: k.graph.entry_states ?? [],
    external_states: k.graph.external_states ?? [],
    verify_key_fields: k.graph.verify_key_fields ?? [],
  },
});

const fromK = (raw: GraphFile, extra: Partial<GraphEntry> = {}): GraphEntry => {
  const k = normalizeGraph(raw);
  return {
    id: k.graph.id,
    name: k.graph.name ?? k.graph.id,
    dom: k.graph.domain ?? '',
    k,
    ...extra,
    draft: extra.draft ? normalizeGraph(extra.draft) : undefined,
  };
};

/** 그래프 목록 = data/graphs (화면에서 한 번 저장한 것은 drafts 로도 와서 배치까지 복원) + 이 화면에서 새로 만든 것 */
export function graphList(D: Data, created: GraphEntry[] = []): GraphEntry[] {
  const out = D.graphs.map((g) => fromK(g));
  D.drafts.forEach((dr) => {
    const g = out.find((x) => x.id === dr.graph.id);
    if (g) g.draft = normalizeGraph(dr);
    else out.push(fromK(dr, { draft: dr, isNew: true }));
  });
  created.filter((c) => !out.some((g) => g.id === c.id)).forEach((c) => out.push(c));
  return out;
}

/** 상태 필드 추정 — 코드 그룹 ID 를 낙타 표기로 바꾼 이름이 조회 응답에 있으면 (SLITM_APRVL_GBCD → slitmAprvlGbcd) */
export function guessField(
  k: { graph: { state_field?: string | null }; code_group?: { id: string } | null },
  ops: Op[],
) {
  if (k.graph.state_field) return { v: k.graph.state_field, why: '그래프에 적힌 값' };
  const camel = (k.code_group?.id ?? '')
    .toLowerCase()
    .replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
  for (const o of ops.filter((o) => o.kind === 'read'))
    for (const r of o.res)
      if (r[0].toLowerCase() === camel.toLowerCase() || r[0].toLowerCase().endsWith(camel.toLowerCase()))
        return { v: r[0], why: `조회 응답 필드 이름이 코드 그룹 ID 와 같음 (${o.sum})` };
  return { v: null, why: '코드 그룹 ID 와 같은 이름의 응답 필드가 없음' };
}

/** 그래프를 처음 열 때 — 저장본이 있으면 그 배치, 없으면 손으로 쓴 그래프 파일을 자동 배치 */
export function initial(g: GraphEntry, ops: Op[]): GState {
  const base: GState = {
    graph: g.id,
    nodes: {},
    edges: [],
    stateField: { v: guessField(g.k, ops).v, st: '추정' },
    saved: null,
  };
  if (g.draft) {
    const dr = g.draft;
    const nodes: Record<string, ENode> = {};
    Object.entries(dr.layout ?? {}).forEach(
      ([c, xy]) => (nodes[String(c)] = { x: xy[0]!, y: xy[1]!, role: 'api' }),
    );
    const edges = dr.transitions
      .map((t) => ({
        from: String(t.from),
        to: String(t.to),
        name: t.name ?? '',
        st: '확정',
        origin: '저장본',
      }))
      .concat(
        dr.external_transitions.map(([a, b]) => ({
          from: String(a),
          to: String(b),
          name: '',
          st: '확정',
          origin: '저장본',
        })),
      );
    return {
      ...base,
      nodes,
      edges,
      saved: dr.version ? { v: dr.version } : null,
      stateField: dr.graph.state_field ? { v: dr.graph.state_field, st: '확정' } : base.stateField,
    };
  }
  const k = g.k;
  const ts = k.transitions;
  const lks = k.lookups ?? [];
  if (!ts.length && !lks.length) return base;
  const codes = k.code_group?.codes ?? {};
  const order = (c: string) => Object.keys(codes).indexOf(c);
  const inT = [...new Set(ts.flatMap((t) => [String(t.from), String(t.to)]))].sort(
    (a, b) => order(a) - order(b),
  );
  const onlyL = [...new Set(lks.flatMap((l) => l.states.map(String)))]
    .filter((c) => !inT.includes(c) && c in codes)
    .sort((a, b) => order(a) - order(b));
  const nodes: Record<string, ENode> = {};
  const W = 180;
  inT.forEach((c, i) => (nodes[c] = { x: 110 + (i % 6) * W, y: 150 + Math.floor(i / 6) * 150, role: 'api' }));
  onlyL.forEach(
    (c, i) => (nodes[c] = { x: 110 + (i % 6) * W, y: 420 + Math.floor(i / 6) * 110, role: 'api' }),
  );
  const edges = ts.map((t) => ({
    from: String(t.from),
    to: String(t.to),
    name: t.name ?? '',
    st: '확정',
    origin: '사람이 확인한 그래프',
  }));
  return {
    ...base,
    nodes,
    edges,
    stateField: k.graph.state_field ? { v: k.graph.state_field, st: '확정' } : base.stateField,
  };
}

/** 공통코드 [코드, 이름] — 공통코드 테이블 전체가 있으면 그것 (저장본은 놓은 상태만 담음), 정렬순서대로 */
export function codesOf(g: GraphEntry, codes: CodeTable[]): [string, string][] {
  const t = codes.find((x) => x.id === g.k.code_group?.id);
  const src = t ?? g.k.code_group ?? { codes: {} as Record<string, string> };
  const order = t ? (t.order ?? Object.keys(src.codes)) : Object.keys(src.codes);
  return order.map((c) => [String(c), src.codes[c] ?? '']);
}

/** 그래프 하나를 다루는 도우미 — 이름 · 순서 · 놓인 상태 · 화살표 */
export function view(g: GraphEntry, s: GState, codes: CodeTable[]) {
  const CODES = codesOf(g, codes);
  const NAME = (c: string) => CODES.find((x) => x[0] === c)?.[1] || c;
  const ORDER = (c: string) => CODES.findIndex((x) => x[0] === c);
  const placed = () => Object.keys(s.nodes).sort((a, b) => ORDER(a) - ORDER(b));
  const edgeOf = (k: string) => s.edges.find((e) => key(e.from, e.to) === k);
  const isExternal = (e: EEdge) => s.nodes[e.from]?.role === 'ext';
  const workEdges = () => s.edges.filter((e) => !isExternal(e));
  const entry = () => Object.keys(s.nodes).find((c) => s.nodes[c]!.role === 'entry') ?? '';
  return {
    CODES,
    NAME,
    ORDER,
    sn: (c: string) => `${c} ${NAME(c)}`,
    placed,
    edgeOf,
    isExternal,
    workEdges,
    entry,
  };
}
export type View = ReturnType<typeof view>;

export type Sel = { kind: 'none' } | { kind: 'node'; id: string } | { kind: 'edge'; id: string };
export interface Issue {
  lv: 'err' | 'warn' | 'info';
  msg: string;
  sel: Sel;
  open?: 'set';
}

/** 다음 할 일 — 노드 흐름만 본다 (API 는 시나리오를 만들 때) */
export function issues(s: GState, v: View): Issue[] {
  const out: Issue[] = [];
  for (const e of v.workEdges()) {
    const sel: Sel = { kind: 'edge', id: key(e.from, e.to) };
    const lab = `${v.NAME(e.from)} → ${v.NAME(e.to)}`;
    if (!e.name) {
      out.push({ lv: 'err', msg: `${lab}: 이 변화를 업무에서 뭐라고 부르는지 적으세요.`, sel });
      continue;
    }
    if (!s.edges.some((r) => r.from === e.to && r.to === e.from && r.name))
      out.push({
        lv: 'warn',
        msg: `${lab}: 되돌리는 화살표가 없어 실행 중 실패하면 이 단계는 되돌릴 수 없습니다 (권한 등급 R2 — 실행할 때마다 확인).`,
        sel,
      });
  }
  if (s.stateField.st !== '확정')
    out.push({
      lv: 'warn',
      msg: s.stateField.v
        ? `현재 상태를 읽는 필드(${s.stateField.v})가 확정 전입니다 (자동 추정). '⋯ 더보기 › 그래프 설정'에서 확인하고 확정하세요.`
        : "현재 상태를 읽는 필드가 없습니다. '그래프 설정'에서 고르세요.",
      sel: { kind: 'none' },
      open: 'set',
    });
  return out;
}

/** 시험해 보기 — 이름 있는 화살표만으로 출발 → (거쳐야 할 상태) → 목표 경로. 없으면 null */
export function search(v: View, start: string, target: string, must: string | null): EEdge[] | null {
  const es = v.workEdges().filter((e) => e.name);
  const first: [string, boolean] = [start, must ? start === must : true];
  const q: [[string, boolean], EEdge[]][] = [[first, []]];
  const seen = new Set([first.join()]);
  while (q.length) {
    const [[c, ok], path] = q.shift()!;
    if (c === target && ok) return path;
    if (path.length >= 12) continue;
    for (const e of es.filter((x) => x.from === c)) {
      const nx: [string, boolean] = [e.to, ok || e.to === must];
      if (!seen.has(nx.join())) {
        seen.add(nx.join());
        q.push([nx, [...path, e]]);
      }
    }
  }
  return null;
}

/** 팔레트를 누르기만 했을 때 놓을 빈 자리 */
export function freeSpot(nodes: Record<string, ENode>) {
  for (const y of [150, 420, 285, 520, 60])
    for (let x = 85; x <= 1010; x += 150)
      if (!Object.values(nodes).some((n) => Math.abs(n.x - x) < 135 && Math.abs(n.y - y) < 70))
        return { x, y };
  return { x: 550, y: 285 };
}

/** 상태 상자를 캔버스 안에 */
export const clampNode = (p: { x: number; y: number }) => ({
  x: clamp(p.x, NW / 2 + 6, VB.w - NW / 2 - 6),
  y: clamp(p.y, NH / 2 + 30, VB.h - NH / 2 - 10),
});

/** 화살표 모양 — 서로 반대 방향 화살표가 있으면 휘게, 상자 테두리에서 시작 · 끝 */
export function geom(a: { x: number; y: number }, b: { x: number; y: number }, both: boolean) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const bend = both ? 34 : 0;
  const cp = { x: (a.x + b.x) / 2 + (dy / len) * bend, y: (a.y + b.y) / 2 - (dx / len) * bend };
  const boundary = (c: { x: number; y: number }, p: { x: number; y: number }, gap: number) => {
    const ddx = p.x - c.x;
    const ddy = p.y - c.y;
    if (!ddx && !ddy) return { x: c.x, y: c.y };
    const t = Math.min(
      ddx ? (NW / 2 + gap) / Math.abs(ddx) : Infinity,
      ddy ? (NH / 2 + gap) / Math.abs(ddy) : Infinity,
    );
    return { x: c.x + ddx * t, y: c.y + ddy * t };
  };
  const s = boundary(a, both ? cp : b, 2);
  const t = boundary(b, both ? cp : a, 7);
  return {
    d: `M${s.x},${s.y} Q${cp.x},${cp.y} ${t.x},${t.y}`,
    lx: (s.x + 2 * cp.x + t.x) / 4,
    ly: (s.y + 2 * cp.y + t.y) / 4,
  };
}

/** 저장할 YAML — 노드 흐름만: 상태 · 화살표 · 업무 이름 (이름 없는 화살표는 빠짐) + 배치 */
export function toYaml(g: GraphEntry, s: GState, v: View): string {
  const q = (x: unknown) => JSON.stringify(String(x));
  const ts = v.workEdges().filter((e) => e.name);
  const skip = v.workEdges().length - ts.length;
  const cg = g.k.code_group!;
  return [
    `# ${g.name} 그래프 — 화면에서 저장 (${s.saved ? `승인본 v${s.saved.v}` : '저장 전 미리보기'}). 노드 흐름만: 상태 · 화살표 · 업무 이름 (이름 없는 화살표 ${skip}개는 빠짐)`,
    `# API 와 '조회로 찾을 수 있는 상태'는 저장하지 않는다 — 시나리오를 만들 때 ② 경로 탐색 · ③ API 선택이 정한다. 사람이 고정한 API · 조회 방법은 서버가 합칠 때 유지된다`,
    `version: ${s.saved ? s.saved.v : 0}`,
    `graph:`,
    `  id: ${g.id}`,
    `  name: ${q(g.name)}`,
    `  domain: ${g.dom}`,
    `  entity: ${q(g.k.graph.entity)}`,
    `  state_field: ${s.stateField.st === '확정' ? s.stateField.v : 'null   # 확정 전이라 빠짐'}`,
    `  entry_states: []   # 정하지 않음 — 찾을 수 있는 상태 중 가장 앞 단계에서 출발`,
    `  verify_key_fields: [${(g.k.graph.verify_key_fields ?? []).join(', ')}]`,
    `code_group:`,
    `  id: ${cg.id}`,
    `  name: ${q(cg.name)}`,
    `  codes:   # 공통코드 전부 — 캔버스에 없는 상태를 고른 요청은 이유와 함께 거절된다`,
    ...v.CODES.map(([c, n]) => `    ${q(c)}: ${q(n)}`),
    `transitions:`,
    ...(ts.length
      ? ts.flatMap((e) => [`  - name: ${q(e.name)}`, `    from: ${q(e.from)}`, `    to: ${q(e.to)}`])
      : [`  []`]),
    `layout:   # 화면 배치`,
    ...v.placed().map((c) => `  ${q(c)}: [${s.nodes[c]!.x}, ${s.nodes[c]!.y}]`),
  ].join('\n');
}

// ─── 새 그래프 ──────────────────────────────────────────────────────────────────────────

/** 아직 그래프로 안 만든 공통코드 그룹 */
export const freeGroups = (graphs: GraphEntry[], codes: CodeTable[]) => {
  const used = new Set(graphs.map((g) => g.k.code_group?.id));
  return codes.filter((c) => !used.has(c.id));
};
export const nameOf = (cg: { id: string; name: string }) => cg.name.replace(/(구분)?코드$/, '') || cg.id;

export function newGraph(cg: CodeTable, name: string, dom: string, entity: string, ops: Op[]): GraphEntry {
  const guess = guessField({ graph: {}, code_group: cg }, ops);
  const k = {
    graph: {
      id: cg.id,
      name,
      domain: dom,
      entity: entity.trim() || name,
      state_field: guess.v,
      entry_states: [],
      external_states: [],
      verify_key_fields: [],
    },
    code_group: cg,
    transitions: [],
    lookups: [],
    external_transitions: [],
  } as GraphFile;
  return fromK(k, { isNew: true });
}

/** 그래프 설정 — 고를 수 있는 상태 필드 (조회 API 응답의 …Gbcd) 와 그 필드를 주는 API 이름 */
export function stateFieldOptions(s: GState, ops: Op[], doms = ['pd', 'od', 'ds']): [string, string[]][] {
  const m = new Map<string, string[]>();
  if (s.stateField.v) m.set(s.stateField.v, []);
  ops
    .filter((o) => o.kind === 'read' && doms.includes(o.dom))
    .forEach((o) =>
      o.res
        .filter((r) => /Gbcd$/.test(r[0]))
        .forEach((r) => {
          if (!m.has(r[0])) m.set(r[0], []);
          m.get(r[0])!.push(o.sum);
        }),
    );
  return [...m];
}
