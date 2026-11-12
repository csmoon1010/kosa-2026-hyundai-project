// 테스트 견본 — 가짜 LLM 서버(tap.cli serve --fake-llm)의 실제 응답을 저장한 것 (2026-11-12, 트레이스 · 미리보기 XML 은 덜어 냄).
// 다시 만들려면 가짜 서버를 띄워 분석 → IR → 등록을 한 번 돌리고 응답을 저장한다.
import type { Schemas } from '../../../api/client';
import analyzeLines from './analyze-stream.json';
import irLines from './ir-stream.json';
import registered from './registered.json';

type AnalyzeResult = Schemas['AnalyzeResult'];
type Line = Record<string, unknown>;

const clone = <T>(x: T): T => structuredClone(x);

export const UTTERANCE = '배송완료된 주문 1건을 배송완료 취소시켜줘';
export const analyzeResult = () =>
  clone((analyzeLines.at(-1) as unknown as { result: AnalyzeResult }).result);
export const irEvents = () => clone(irLines) as unknown as Line[];
export const irFile = () => (irEvents().at(-1) as { result: { file: string } }).result.file;
export const reviewFile = () => (irEvents()[0] as { filename: string }).filename;
export const registerResult = () => clone(registered.register) as unknown as Schemas['RegisterResult'];
export const record = () => clone(registered.record) as unknown as Schemas['RegisteredRecord'];
export const scenarioList = () => clone(registered.list) as unknown as Schemas['ScenarioList'];

/** 분석 스트림 — 단계 3줄 + 마지막 줄(result) */
export function analyzeStream(result: AnalyzeResult | { error: string } = analyzeResult()) {
  const event = 'error' in result && typeof result.error === 'string' ? 'error' : 'done';
  return ['intent', 'paths', 'apis']
    .map((stage) => JSON.stringify({ event: 'stage', stage }) + '\n')
    .concat(JSON.stringify({ event, result }) + '\n');
}

export const irStream = (events: Line[] = irEvents()) => events.map((e) => JSON.stringify(e) + '\n');

/** 확인할 것이 있는 결과 — 2번째 단계(1-1)를 LLM 이 골랐고 되돌릴 수 없음(R2) */
export function withConfirm(): AnalyzeResult {
  const r = analyzeResult();
  r.gate.need_steps = ['1-1'];
  const step = r.gate.steps.find((s) => s.key === '1-1')!;
  step.requirement = '단계 승인';
  step.tier = 'R2';
  r.apis.unresolved = [
    { path_sequence: 1, step: 1, reason: 'ValueError: LLM 이 고른 API — 확인 필요 [LLM_PICK]' },
  ];
  return r;
}

export function blocked(): AnalyzeResult {
  const r = analyzeResult();
  r.gate.status = '차단';
  r.gate.blocked = ['1-1 출고취소처리: R3 — 실행 금지 API'];
  return r;
}

/** 필드 한글 이름 — 입력값 표의 '필드설명' */
export const operations = (): Schemas['OperationsPart'] => ({
  ops: [
    {
      id: 'hshop-openapi:POST:/sc/scb/scbd/selectOshpDtlList.do',
      path: '/sc/scb/scbd/selectOshpDtlList.do',
      sum: '출고조회',
      kind: 'read',
      dom: 'ds',
      req: [['oauserId', '사용자ID', '']],
      res: [],
    },
  ],
});

export const environment = (catalogVersion = 3): Schemas['EnvironmentPart'] => ({
  generated_at: '2026-11-12T21:00:00+09:00',
  build: {
    operations: 43,
    catalog_version: catalogVersion,
    spec_sources: [],
    kinds: {},
    domains: {},
    review: 0,
  },
  connections: [],
  tools: [],
});
