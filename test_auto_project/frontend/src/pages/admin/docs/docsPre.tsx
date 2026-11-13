/* eslint-disable react-refresh/only-export-components -- 문서 본문을 만드는 함수 모듈 — 화면 컴포넌트를 내보내지 않는다 (안의 작은 부품은 이 파일에서만 쓴다) */
// 데이터 조회 — 전처리 산출물 4종 (혜정, web/preprocessing-ui.js 의 REAL_DOCS · 필터를 그대로)
// Canonical Schema · Baseline Request · Parameter KB · Response Outputs — 경로 · 타입 · 승인 상태를 유지한 조회.
import { Fragment, type ReactNode } from 'react';

import type { Schemas } from '../../../api/client';
import type { AdminData } from '../adminData';
import styles from '../admin.module.css';
import { Tbl } from '../parts';
import { REAL_DOM } from '../scope';
import type { DocResult } from './docsBase';

type Pre = Schemas['Preprocessing'];
type Canonical = Schemas['PreCanonical'];
type Field = Schemas['PreField'];
export interface ArtifactFilter {
  domain?: string;
  document?: string;
  api?: string;
}

export const DOMAIN_NAMES: Record<string, string> = {
  pd: '상품',
  od: '주문',
  ds: '물류',
  af: '재경',
  cs: '상담',
  hm: '전시',
  unknown: '미분류',
};

const Code = ({ value }: { value: unknown }) => (
  <code className={styles.path}>{value == null ? '—' : String(value)}</code>
);
const textValue = (value: unknown) =>
  value === undefined ? '—' : typeof value === 'string' ? value : JSON.stringify(value);
const required = (f: {
  required?: boolean | null;
  requiredDeclared?: boolean | null;
  required_declared?: boolean | null;
}) => ((f.requiredDeclared ?? f.required_declared) ? (f.required ? '필수' : '선택') : '미명시');
const Empty = () => <p className="note">해당 JSON 산출물이 없습니다. 전처리 실행 후 갱신해 주세요.</p>;

/** 산출물 조회 도우미 — 전처리 · 메타데이터에 묶인다 */
export function preHelpers(pre: Pre, a: AdminData) {
  const apiDomain = (sid: string) => a.meta.find((m) => m.api_id === sid)?.domain ?? 'unknown';
  const documentId = (sid: string, c: Canonical) => c.documentId || sid.split(':', 1)[0]!;
  const apis = (dom: string | null) =>
    Object.entries(pre.canonical_schema).filter(
      ([sid]) => !dom || a.meta.some((m) => m.api_id === sid && m.domain === REAL_DOM[dom]),
    );
  const filtered = (dom: string | null, f: ArtifactFilter) =>
    apis('domain' in f ? null : dom).filter(
      ([sid, c]) =>
        (!f.domain || apiDomain(sid) === f.domain) &&
        (!f.document || documentId(sid, c) === f.document) &&
        (!f.api || sid === f.api),
    );
  const apiName = (sid: string, c: Canonical) =>
    a.meta.find((m) => m.api_id === sid)?.api_name || c.summary || c.operationId || c.apiId;
  return { apiDomain, documentId, apis, filtered, apiName };
}

function Heading({ sid, name, extra }: { sid: string; name: string; extra?: ReactNode }) {
  return (
    <>
      <h3 className={styles.artifactTitle}>
        {name} {extra}
      </h3>
      <p>
        <Code value={sid} />
      </p>
    </>
  );
}

function FieldsTable({ fields, valueKey }: { fields: Field[]; valueKey: 'value' | 'example' }) {
  return (
    <Tbl
      head={[
        '필드 · 위치',
        'parameter_path',
        'xmlPath',
        '타입',
        '필수여부',
        valueKey === 'value' ? '값 · 출처' : 'example',
      ]}
      empty="필드가 없습니다."
      rows={fields.map((p, i) => (
        <tr key={i}>
          <td>
            {p.name || ''}
            <br />
            <span className="note">{p.location || ''}</span>
          </td>
          <td>
            <Code value={p.parameter_path} />
          </td>
          <td>
            <Code value={p.xmlPath} />
          </td>
          <td>
            <Code value={p.type} />
          </td>
          <td>{required(p)}</td>
          <td>
            {textValue(p[valueKey])}
            {valueKey === 'value' && (
              <>
                <br />
                <span className="note">{p.value_source || ''}</span>
              </>
            )}
          </td>
        </tr>
      ))}
    />
  );
}

export function schemaDoc(pre: Pre, a: AdminData, dom: string | null, f: ArtifactFilter = {}): DocResult {
  const h = preHelpers(pre, a);
  const entries = h.filtered(dom, f);
  return {
    count: `API ${entries.length}개 · 필드 ${entries.reduce((n, [, c]) => n + c.parameters.length, 0)}개`,
    body: entries.length ? (
      entries.map(([sid, c]) => (
        <Fragment key={sid}>
          <Heading sid={sid} name={h.apiName(sid, c)} />
          <p className="note">
            {c.contentType || '본문 없음'} · 요청 본문 {c.requestBodyRequired ? '필수' : '선택/미명시'}
          </p>
          <FieldsTable fields={c.parameters} valueKey="example" />
        </Fragment>
      ))
    ) : (
      <Empty />
    ),
  };
}

export function baselineDoc(pre: Pre, a: AdminData, dom: string | null, f: ArtifactFilter = {}): DocResult {
  const h = preHelpers(pre, a);
  const entries = h.filtered(dom, f);
  const count = entries.filter(([sid]) => pre.baselines[sid]?.user_registered).length;
  return {
    count: `${count} / ${entries.length} 사용자 등록`,
    body: entries.length ? (
      entries.map(([sid, c]) => {
        const b = pre.baselines[sid];
        return (
          <Fragment key={sid}>
            <Heading
              sid={sid}
              name={h.apiName(sid, c)}
              extra={<span className="tag">{b?.user_registered ? '사용자 등록' : '예시 초안 · 미등록'}</span>}
            />
            {b ? <FieldsTable fields={b.parameters} valueKey="value" /> : <Empty />}
          </Fragment>
        );
      })
    ) : (
      <Empty />
    ),
  };
}

type KbParam = {
  identity: { document_id?: string; api_id?: string; parameter_path?: string; parameter_name?: string };
  knowledge: { description?: string };
  schema: { xml_path?: string; type?: string; required?: boolean; required_declared?: boolean };
};
type Knowledge = {
  kind?: string;
  payload?: unknown;
  targets?: { document_id?: string; api_id?: string; parameter_path?: string }[];
  application_scope?: { type?: string; domain_id?: string };
};

export function pkbDoc(pre: Pre, a: AdminData, dom: string | null, f: ArtifactFilter = {}): DocResult {
  const h = preHelpers(pre, a);
  const entries = h.filtered(dom, f);
  const fields = entries.reduce((n, [sid]) => n + (pre.parameter_kb[sid]?.parameters.length || 0), 0);
  const scopeNames: Record<string, string> = { pd: 'product', od: 'order', ds: 'logistics' };
  const domain =
    ('domain' in f ? f.domain : dom ? REAL_DOM[dom] : '') || a.meta.find((m) => m.api_id === f.api)?.domain;
  const scopeIds = [
    domain,
    domain && scopeNames[domain],
    Object.keys(REAL_DOM).find((k) => REAL_DOM[k] === domain),
  ].filter(Boolean);
  const common = (pre.common_knowledge as Knowledge[]).filter(
    (k) =>
      !domain ||
      k.application_scope?.type === 'GLOBAL' ||
      scopeIds.includes(k.application_scope?.domain_id ?? ''),
  );
  return {
    count: `기본 필드 ${fields}개`,
    body: (
      <>
        {entries.map(([sid, c]) => {
          const kb = pre.parameter_kb[sid];
          if (!kb)
            return (
              <Fragment key={sid}>
                <Heading sid={sid} name={h.apiName(sid, c)} />
                <Empty />
              </Fragment>
            );
          const knowledge = kb.api_knowledge as Knowledge[];
          return (
            <Fragment key={sid}>
              <Heading sid={sid} name={h.apiName(sid, c)} />
              <Tbl
                head={[
                  '필드 · 기본 의미',
                  'parameter_path',
                  'xmlPath',
                  '타입',
                  '필수여부',
                  '승인된 API 지식',
                ]}
                empty="기본 지식이 없습니다."
                rows={(kb.parameters as KbParam[]).map((p, i) => {
                  const id = p.identity;
                  const approved = knowledge.filter((k) =>
                    (k.targets ?? []).some(
                      (t) =>
                        t.document_id === id.document_id &&
                        t.api_id === id.api_id &&
                        t.parameter_path === id.parameter_path,
                    ),
                  );
                  return (
                    <tr key={i}>
                      <td>
                        {id.parameter_name}
                        <br />
                        <span className="note">{p.knowledge.description || ''}</span>
                      </td>
                      <td>
                        <Code value={id.parameter_path} />
                      </td>
                      <td>
                        <Code value={p.schema.xml_path} />
                      </td>
                      <td>
                        <Code value={p.schema.type} />
                      </td>
                      <td>{required(p.schema)}</td>
                      <td>
                        {approved.length ? (
                          approved.map((k, j) => (
                            <p key={j}>
                              <b>{k.kind}</b>
                              <br />
                              {textValue(k.payload)}
                            </p>
                          ))
                        ) : (
                          <span className="note">승인 보강 지식 없음 · Canonical 기본 지식</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              />
            </Fragment>
          );
        })}
        <h3 className={styles.artifactTitle}>승인된 공통 지식</h3>
        <Tbl
          head={['종류', '적용 범위', '내용']}
          empty="해당 범위의 승인된 공통 지식이 없습니다."
          rows={common.map((k, i) => (
            <tr key={i}>
              <td>{k.kind}</td>
              <td>{textValue(k.application_scope)}</td>
              <td>{textValue(k.payload)}</td>
            </tr>
          ))}
        />
      </>
    ),
  };
}

type Output = {
  name?: string;
  parameter_path?: string;
  xmlPath?: string;
  response_path?: string;
  type?: string;
  required?: boolean;
  requiredDeclared?: boolean;
  response_key?: string;
  content_type?: string;
};
type Resp = { response_key?: string; status_code?: string; content_type?: string };

export function respDoc(pre: Pre, a: AdminData, dom: string | null, f: ArtifactFilter = {}): DocResult {
  const h = preHelpers(pre, a);
  const entries = h.filtered(dom, f);
  return {
    count: `활성 성공 필드 ${entries.reduce((n, [sid]) => n + (pre.response_outputs[sid]?.outputs.length || 0), 0)}개`,
    body: entries.length ? (
      entries.map(([sid, c]) => {
        const r = pre.response_outputs[sid];
        if (!r)
          return (
            <Fragment key={sid}>
              <Heading sid={sid} name={h.apiName(sid, c)} />
              <Empty />
            </Fragment>
          );
        const responses = r.responses as Resp[];
        return (
          <Fragment key={sid}>
            <Heading sid={sid} name={h.apiName(sid, c)} />
            <p className="note">
              허용 성공 응답:{' '}
              {responses
                .map((x) => `${x.response_key} · HTTP ${x.status_code} · ${x.content_type}`)
                .join(', ') || '없음'}
            </p>
            <Tbl
              head={['출력', 'parameter_path', 'xmlPath / response_path', '타입', '필수여부', '성공 응답']}
              empty="사용 가능한 활성 성공응답 필드가 없습니다."
              rows={(r.outputs as Output[]).map((p, i) => (
                <tr key={i}>
                  <td>{p.name}</td>
                  <td>
                    <Code value={p.parameter_path} />
                  </td>
                  <td>
                    <Code value={p.xmlPath || p.response_path} />
                  </td>
                  <td>
                    <Code value={p.type} />
                  </td>
                  <td>{required(p)}</td>
                  <td>
                    {p.response_key}
                    <br />
                    {p.content_type}
                  </td>
                </tr>
              ))}
            />
            <details>
              <summary>성공 응답 스키마</summary>
              <pre className={`${styles.code} ${styles.artifactJson}`}>
                {JSON.stringify(r.responses, null, 2)}
              </pre>
            </details>
          </Fragment>
        );
      })
    ) : (
      <Empty />
    ),
  };
}
