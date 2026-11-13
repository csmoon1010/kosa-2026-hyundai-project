// 규칙 입력 — 저장 대상 · 항목 · 대상 · 검증 (예전 화면의 RULE_ITEMS · ALLOWED · targetsFor · validateRuleX, 실제 데이터 모드 값)
import type { AdminData, Rule } from '../adminData';
import { apiLabel } from '../adminData';
import type { Check } from '../parts';

export type Place = 'am' | 'ov'; // am 전사 · ov 도메인
export type DocKey = 'sv' | 'pkb' | 'cat' | 'meta';
/** [항목 key, 이름, 예시(placeholder), 설명] */
export type ItemMeta = readonly [string, string, string, string];

export const RULE_ITEMS: Record<DocKey, ItemMeta[]> = {
  sv: [
    [
      'syn',
      '동의어',
      '발송된, 보낸, 택배 출발',
      '자연어에서 이 상태를 가리키는 다른 표현. 쉼표로 여러 개. 시나리오 생성 때 LLM 에게 상태 목록과 함께 보여 주어 목표 상태를 고르는 정확도를 올린다 — 고르는 값은 여전히 상태 이름 안에서만.',
    ],
  ],
  pkb: [
    ['def', '기본값', 'pay_plan_cd=01 (일반결제)', '필드 = 값. 대상이 적용 범위를 결정한다.'],
    [
      'cond',
      '조건부 필수',
      'offline_yn=Y → offline_sale_price',
      '조건이 성립하면 필수가 되는 필드. 명세로는 표현할 수 없다.',
    ],
    ['alias', '별칭', 'ordNo, ORD_NO', '같은 개념의 다른 필드명. 의존성 추출에 쓰인다.'],
    ['meaning', '의미', '배송 유형', '필드의 업무적 의미. 명세 설명이 부실할 때 보충한다.'],
    ['value', '값 해석', '01 단건배송 · 02 분할배송', '코드값의 뜻. 필드 매핑 단계에서 모델에게 제시된다.'],
  ],
  cat: [
    [
      'desc',
      '설명 보정',
      '결제 승인 — PG 승인까지 완료',
      '명세 summary 가 부실할 때 한 줄 설명을 바꾼다 (overrides description).',
    ],
    [
      'kw',
      '검색어 · 별칭',
      '출고, 발송, 배송 시작',
      '업무 용어를 별칭으로 붙인다 (overrides aliases). 시나리오를 만들 때 ③ API 선택의 후보 찾기에 쓰인다. 쉼표로 여러 개.',
    ],
    [
      'excl',
      '제외',
      '내부 배치 전용 — 테스트 데이터 생성에 쓰지 않음',
      '사용 안 함으로 바꿔 Agent 후보에서 뺀다 (overrides enabled: false). 사유를 적는다.',
    ],
  ],
  meta: [
    [
      'irrev',
      '되돌림 불가',
      '불가 외부 물류사로 전송되어 되돌릴 수 없음',
      '불가 · 가능 · 미확인 중 하나로 시작하고 뒤에 사유. 경로에 포함되면 승인 화면에 경고가 뜬다 (overrides irreversible).',
    ],
    [
      'memo',
      '구별 메모',
      '단건 등록. 여러 건은 bulk 사용',
      '비슷한 API 와의 차이. API 후보를 고를 때 참고한다 (overrides memo).',
    ],
    [
      'sel',
      '구분값',
      'procGb: PB2 출고완료취소 · PB3 배송완료취소',
      '한 API 가 여러 일을 할 때 이번 일을 고르는 값 — 「필드: 값 이름 · 값 이름」, 목록이 일부면 끝에 (일부). 상태 그래프 화살표의 API 자동 찾기에 쓰인다 (overrides selectors).',
    ],
  ],
};

export const DOC_LABEL: Record<DocKey, string> = {
  sv: 'State Vocabulary',
  pkb: 'Parameter KB',
  cat: 'API Catalog',
  meta: 'API MetaData',
};

/** 저장 대상 고르기 — 전사는 Parameter KB 만 */
export const DOC_OPTIONS: Record<Place, [DocKey, string][]> = {
  ov: [
    ['sv', 'State Vocabulary — 상태 지식'],
    ['pkb', 'Parameter KB — 파라미터 지식'],
    ['cat', 'API Catalog — 카탈로그 보정'],
    ['meta', 'API MetaData — API 속성'],
  ],
  am: [['pkb', 'Parameter KB — 파라미터 지식']],
};

export const ALLOWED: Record<Place, Partial<Record<DocKey, string[]>>> = {
  ov: { sv: ['syn'], pkb: ['def', 'cond'], cat: ['desc', 'kw', 'excl'], meta: ['irrev', 'memo', 'sel'] },
  am: { pkb: ['alias', 'meaning', 'value', 'def'] },
};
const OTHER_HOME: Record<Place, string> = {
  ov: '관리자 메뉴 › 전사 › 규칙 입력',
  am: '관리자 메뉴 › 각 도메인 › 규칙 입력',
};

export const itemMeta = (doc: DocKey, key: string) => RULE_ITEMS[doc].find((x) => x[0] === key);
export const isAllowed = (place: Place, doc: DocKey, item: string) =>
  Boolean(ALLOWED[place][doc]?.includes(item));

/** 대상 칸 이름 */
export const targetLabel = (doc: DocKey, item: string) =>
  doc === 'sv'
    ? '대상 상태'
    : doc === 'meta' || doc === 'cat'
      ? '대상 API'
      : item === 'def' || item === 'cond'
        ? '적용 지점'
        : '대상 필드';

/** 대상 목록 [값, 이름] — 상태 · API · 적용 지점(그래프 화살표) · 필드 */
export function targetsFor(
  a: AdminData,
  place: Place,
  dom: string | null,
  doc: DocKey,
  item: string,
): [string, string][] {
  const d = place === 'ov' ? dom : null;
  if (doc === 'sv')
    return a
      .graphsOf(d)
      .flatMap((g) =>
        Object.entries(g.code_group?.codes ?? {}).map(
          ([c, n]) =>
            [`${g.graph.id}:${c}`, `${g.graph.name} (${g.code_group?.id}) · ${c} ${n}`] as [string, string],
        ),
      );
  if (doc === 'meta' || doc === 'cat') return a.metaOf(d).map((m) => [m.api_id, apiLabel(m)]);
  const trans = a
    .graphsOf(d)
    .flatMap((g) =>
      g.transitions.map(
        (t) =>
          [`${g.graph.id}:${t.from}>${t.to}`, `${g.graph.name} · ${t.name} (${t.from}→${t.to})`] as [
            string,
            string,
          ],
      ),
    );
  if (item === 'def')
    return [
      ...((place === 'am' ? [['전역', '전역']] : [['도메인 전체', '도메인 전체']]) as [string, string][]),
      ...trans,
    ];
  if (item === 'cond') return trans;
  const seen = new Map<string, string | null>();
  a.metaOf(d).forEach((m) =>
    a.opsOf(m.api_id).req.forEach(([n, l]) => {
      if (!seen.has(n)) seen.set(n, l);
    }),
  );
  return [...seen].sort((x, y) => x[0].localeCompare(y[0])).map(([n, l]) => [n, l ? `${n} · ${l}` : n]);
}

/** 「코드 뜻 · 코드 뜻」 → [[코드, 뜻] …] */
export const parseCodes = (s: string) =>
  String(s)
    .split('·')
    .map((t) => t.trim())
    .filter(Boolean)
    .map((t) => {
      const m = t.match(/^(\S+)\s+(.+)$/);
      return m ? [m[1]!, m[2]!.trim()] : [t, ''];
    });

/** 저장 시점 검증 — 이 메뉴에서 넣는 항목인가 · 대상 · 내용 · 항목별 형식 */
export function validateRule(
  a: AdminData,
  place: Place,
  doc: DocKey,
  item: string,
  tgt: string,
  body: string,
): Check[] {
  const out: Check[] = [];
  const name = itemMeta(doc, item)?.[1] ?? item;
  const ok = isAllowed(place, doc, item);
  out.push([
    ok,
    ok
      ? `${DOC_LABEL[doc]} · ${name} 는 이 메뉴에서 등록한다`
      : `${name} 는 ${OTHER_HOME[place]} 에서 등록한다`,
  ]);
  out.push([Boolean(tgt), tgt ? `대상 ${tgt}` : '대상을 선택해야 한다']);
  out.push([Boolean(body), body ? '내용 확인' : '내용이 비어 있다']);
  if (item === 'def')
    out.push([body.includes('='), body.includes('=') ? '필드 = 값 형식 확인' : '필드 = 값 형식이어야 한다']);
  if (item === 'value' && body) {
    const ok2 = parseCodes(body).every(([c, l]) => c && l);
    out.push([
      ok2,
      ok2 ? '코드 뜻 형식 확인' : '「코드 뜻 · 코드 뜻」 형식이어야 한다 (예: 04 새벽배송 · 05 정기배송)',
    ]);
  }
  if (item === 'cond')
    out.push([
      body.includes('→'),
      body.includes('→') ? '조건 → 필수 필드 형식' : '화살표(→)로 조건과 필수 필드를 구분해야 한다',
    ]);
  if (doc === 'meta' && item === 'irrev') {
    const ok3 = ['불가', '가능', '미확인'].includes((body || '').split(/\s+/)[0] ?? '');
    out.push([ok3, ok3 ? '불가 · 가능 · 미확인 확인' : '불가 · 가능 · 미확인 중 하나로 시작해야 한다']);
  }
  if (doc === 'meta' && item === 'sel') {
    const mm = (body || '').match(/^\s*([A-Za-z_]\w*)\s*:\s*(.+)$/);
    const f = mm?.[1];
    const has = Boolean(f && a.opsOf(tgt).req.some((r) => r[0] === f));
    out.push([
      Boolean(mm),
      mm ? '「필드: 값 이름」 형식 확인' : '「필드: 값 이름 · 값 이름」 형식이어야 한다',
    ]);
    if (mm) out.push([has, has ? `${f} 는 이 API 의 요청 필드` : `${f} 는 이 API 의 요청 필드가 아니다`]);
  }
  return out;
}

/** 저장 성공 알림 — 저장 대상마다 언제 쓰이는지 */
export function savedMessage(doc: DocKey, item: string, catalogVersion: unknown) {
  const where =
    doc === 'cat' || doc === 'meta'
      ? ` · 다시 빌드 (catalog v${catalogVersion})`
      : doc === 'sv'
        ? ' · 다음 시나리오 생성부터 목표 추출에 쓰입니다'
        : ' (이 값을 쓰는 단계는 아직 없음)';
  return `${DOC_LABEL[doc]} · ${itemMeta(doc, item)?.[1]} 저장 — data/config/rules.ui.yaml${where}`;
}

// ─── 등록된 내역 ───────────────────────────────────────────────────────────────────────

const META_KEY_LABEL: Record<string, [DocKey, string]> = {
  description: ['cat', 'desc'],
  aliases: ['cat', 'kw'],
  enabled: ['cat', 'excl'],
  irreversible: ['meta', 'irrev'],
  memo: ['meta', 'memo'],
  selectors: ['meta', 'sel'],
};

export interface RuleRow {
  doc: DocKey;
  item: string;
  target: string;
  label: string;
  body: string;
  by: string;
  at: string;
  /** 화면에서 넣은 규칙 — 지울 수 있다 */
  id?: number;
}

/** 등록된 내역 — overrides.yaml(도메인만) + 화면 규칙, 저장 대상 순서로 */
export function ruleRows(a: AdminData, place: Place, dom: string | null): RuleRow[] {
  const d = place === 'ov' ? dom : null;
  const apis = new Set(a.metaOf(d).map((m) => m.api_id));
  const label = (doc: DocKey, t: string) => {
    if (doc === 'meta' || doc === 'cat') {
      const m = a.meta.find((x) => x.api_id === t);
      return m ? apiLabel(m) : t;
    }
    if (doc === 'sv') {
      const [gid, c] = String(t).split(':');
      const g = a.graphsOf(null).find((x) => x.graph.id === gid);
      return g ? `${g.graph.name} (${g.code_group?.id}) · ${c} ${g.code_group?.codes[c ?? ''] || ''}` : t;
    }
    return t;
  };
  const ui = a.rules.filter((r: Rule) => r.place === place && (place === 'am' || r.dom === d));
  const file: RuleRow[] =
    place === 'am'
      ? []
      : Object.entries(a.env.overrides_file ?? {})
          .filter(([api]) => apis.has(api))
          .flatMap(([api, ov]) =>
            Object.entries(ov).map(([k, v]) => {
              const [doc, item] = META_KEY_LABEL[k] ?? (['meta', k] as [DocKey, string]);
              const body =
                k === 'selectors'
                  ? (v as { field: string; values?: { value: string; name?: string }[] }[])
                      .map(
                        (x) =>
                          `${x.field}: ${(x.values ?? []).map((y) => `${y.value}${y.name ? ' ' + y.name : ''}`).join(' · ')}`,
                      )
                      .join(' / ')
                  : Array.isArray(v)
                    ? v.join(', ')
                    : String(v);
              return {
                doc,
                item,
                target: api,
                label: label(doc, api),
                body,
                by: 'overrides.yaml',
                at: '사람 편집',
              };
            }),
          );
  const rows: RuleRow[] = [
    ...file,
    ...ui.map((r) => ({
      doc: r.doc as DocKey,
      item: r.item,
      target: r.target ?? '',
      label: label(r.doc as DocKey, r.target ?? ''),
      body: r.body ?? '',
      by: r.by ?? '',
      at: r.at ?? '',
      id: r.id,
    })),
  ];
  const ord: Record<DocKey, number> = { sv: 0, pkb: 1, cat: 2, meta: 3 };
  return rows.sort((x, y) => ord[x.doc] - ord[y.doc]);
}
