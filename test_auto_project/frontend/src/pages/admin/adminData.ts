// 관리자 화면이 같이 쓰는 데이터와 도우미 — 예전 화면의 realMeta · realGraphs · graphsOf · opsOf · apiLabel
import type { Schemas } from '../../api/client';
import {
  useBaselines,
  useCatalog,
  useEnvironment,
  useGraphs,
  useMetadata,
  useOperations,
  useReview,
  useRules,
} from '../../api/queries';
import { shortApi } from '../../lib/format';
import { normalizeGraph } from './graph/editorModel';
import { REAL_DOM } from './scope';

export type Meta = Schemas['ApiMetadata'];
export type Graph = Schemas['GraphFile'];
export type Rule = Schemas['UiRule'];
type Op = Schemas['OperationDigest'];

export const apiLabel = (m: { api_name: string; api_id: string }) =>
  `${m.api_name} · ${shortApi(m.api_id).split('/').pop()}`;

/** 관리자 화면 데이터 한 번에 — 하나라도 받는 중이면 ready=false */
export function useAdminData() {
  const env = useEnvironment();
  const catalog = useCatalog();
  const metadata = useMetadata();
  const ops = useOperations();
  const review = useReview();
  const rules = useRules();
  const graphs = useGraphs();
  const baselines = useBaselines();
  const all = [env, catalog, metadata, ops, review, rules, graphs, baselines];
  const error = all.find((q) => q.isError)?.error ?? null;
  if (
    !env.data ||
    !catalog.data ||
    !metadata.data ||
    !ops.data ||
    !review.data ||
    !rules.data ||
    !graphs.data ||
    !baselines.data
  )
    return { ready: false as const, error };

  const meta = metadata.data.metadata;
  const savedGraphs = graphs.data.graphs.map(normalizeGraph);
  const drafts = graphs.data.drafts.map(normalizeGraph);
  const d = {
    env: env.data,
    build: env.data.build,
    catalog: catalog.data.catalog,
    meta,
    ops: ops.data.ops,
    review: review.data.review,
    rules: rules.data.rules,
    graphs: savedGraphs,
    drafts,
    baselines: baselines.data.baselines,
  };
  return {
    ready: true as const,
    error,
    ...d,
    /** 이 도메인(화면 id: order · goods · logistics)으로 분류된 API. null 이면 전체 */
    metaOf: (dom: string | null): Meta[] => meta.filter((m) => !dom || m.domain === REAL_DOM[dom]),
    /** 이 도메인이 주인인 상태 그래프 (data/graphs) */
    graphsIn: (dom: string | null): Graph[] =>
      savedGraphs.filter((g) => !dom || g.graph.domain === REAL_DOM[dom]),
    /** 그래프 + 화면에서 저장한 것 중 data/graphs 에 없는 것 */
    graphsOf: (dom: string | null): Graph[] =>
      [...savedGraphs, ...drafts.filter((x) => !savedGraphs.some((g) => g.graph.id === x.graph.id))].filter(
        (g) => !dom || g.graph.domain === REAL_DOM[dom],
      ),
    opsOf: (api: string): Pick<Op, 'req' | 'res'> & Partial<Op> =>
      ops.data.ops.find((o) => o.id === api) ?? { req: [], res: [] },
  };
}

export type AdminData = Extract<ReturnType<typeof useAdminData>, { ready: true }>;

/** 범위 탭 아래 작은 글씨 — 그래프 · API 수 */
export function scopeSub(a: AdminData, dom: string) {
  const n = a.metaOf(dom).length;
  const g = a.graphsIn(dom).length;
  return g ? `그래프 ${g}${n ? ` · API ${n}` : ''}` : n ? `API ${n} · 그래프 없음` : 'API 없음';
}

export const selStr = (sel: Record<string, string> | null | undefined) =>
  Object.entries(sel ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .join(', ');
