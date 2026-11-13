// 데이터 조회 문서 8종 — 이름 · 역할 · 본문 함수. 전처리 4종(혜정)은 전처리 산출물을 받은 뒤
import { usePreprocessing } from '../../../api/queries';
import type { AdminData } from '../adminData';
import { catalogDoc, metaDoc, svDoc, toolDoc, type DocResult } from './docsBase';
import { baselineDoc, pkbDoc, respDoc, schemaDoc, type ArtifactFilter } from './docsPre';

export const DOCS = [
  ['catalog', 'API Catalog', '엔드포인트와 한 줄 설명'],
  ['meta', 'API MetaData', 'API별 성격 · 되돌림 불가 · 구별 메모'],
  ['schema', 'Canonical Schema', 'Swagger 를 정규화한 요청 필드와 타입'],
  ['tool', 'Tool Registry', '실행기가 호출하는 도구 목록'],
  ['baseline', 'Baseline Request', '예시 기본값 · 사용자 등록 요청값'],
  ['pkb', 'Parameter KB', '필드 의미 · 별칭 · 값 해석 · 기본값'],
  ['resp', 'Response Outputs', '응답에서 꺼내 다음 호출에 넘기는 값'],
  ['sv', 'State Vocabulary', '그래프 노드가 되는 상태 · 동의어 · 검증'],
] as const;
export type DocId = (typeof DOCS)[number][0];

export const PRE_DOCS = { schema: schemaDoc, baseline: baselineDoc, pkb: pkbDoc, resp: respDoc } as const;
export const BASE_DOCS = { catalog: catalogDoc, meta: metaDoc, tool: toolDoc, sv: svDoc } as const;
export const isPre = (id: DocId): id is keyof typeof PRE_DOCS => id in PRE_DOCS;

/** 문서 하나의 건수 · 본문 — 전처리 4종은 전처리 산출물을 받은 뒤 */
export function useDoc(a: AdminData) {
  const pre = usePreprocessing();
  return (id: DocId, dom: string | null, filter?: ArtifactFilter): DocResult | null => {
    if (!isPre(id)) return BASE_DOCS[id](a, dom);
    return pre.data ? PRE_DOCS[id](pre.data.preprocessing, a, dom, filter) : null;
  };
}
