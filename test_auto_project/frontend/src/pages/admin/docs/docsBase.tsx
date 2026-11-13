/* eslint-disable react-refresh/only-export-components -- 문서 본문을 만드는 함수 모듈 — 화면 컴포넌트를 내보내지 않는다 (안의 작은 부품은 이 파일에서만 쓴다) */
// 데이터 조회 — API Catalog · API MetaData · Tool Registry · State Vocabulary (예전 화면의 REAL_DOCS 4종)
import type { ReactNode } from 'react';

import { domName, shortApi } from '../../../lib/format';
import { selStr, type AdminData } from '../adminData';
import styles from '../admin.module.css';
import { Muted, Tbl } from '../parts';
import { noApi } from '../scope';

export interface DocResult {
  count: string;
  body: ReactNode;
}

const Note = ({ children }: { children: ReactNode }) => <p className={styles.docNote}>{children}</p>;

export function catalogDoc(a: AdminData, dom: string | null): DocResult {
  const ms = a.metaOf(dom);
  const all = !dom;
  const by = new Map(a.catalog.map((c) => [c.api_id, c]));
  const src = (a.build.spec_sources[0] ?? {}) as { document_id?: string };
  return {
    count: ms.length ? `API ${ms.length}개 · catalog v${a.build.catalog_version}` : '',
    body: (
      <>
        <Tbl
          head={[...(all ? ['도메인'] : []), 'API', '엔드포인트', '쓰기/조회', '별칭', '사용']}
          empty={noApi(dom)}
          rows={ms.map((m) => {
            const c = by.get(m.api_id) ?? { ...m, tool_enabled: m.tool_enabled };
            return (
              <tr key={m.api_id}>
                {all && <td className="v">{domName(m.domain)}</td>}
                <td style={{ fontSize: 12.5 }}>{c.api_name}</td>
                <td className={styles.f}>{shortApi(m.api_id)}</td>
                <td className="v">{m.kind === 'write' ? '쓰기' : '조회'}</td>
                <td style={{ fontSize: 11.5 }}>{c.aliases?.length ? c.aliases.join(', ') : <Muted />}</td>
                <td className="v">
                  {c.tool_enabled ? '사용' : <span className={styles.danger}>안 함</span>}
                </td>
              </tr>
            );
          })}
        />
        <Note>입력 명세: {src.document_id ?? ''} (공개 OpenAPI, 내부 명세로 교체 예정).</Note>
      </>
    ),
  };
}

export function metaDoc(a: AdminData, dom: string | null): DocResult {
  const ms = a.metaOf(dom);
  const all = !dom;
  const nsel = ms.filter((m) => (m.selectors ?? []).length).length;
  return {
    count: ms.length ? `API ${ms.length}개 · 구분값 있는 API ${nsel}개` : '',
    body: (
      <>
        <Tbl
          head={[
            ...(all ? ['도메인'] : []),
            'API',
            '동작',
            '구분값 (selectors)',
            '되돌림 불가',
            '구별 메모',
            '버전',
          ]}
          empty={noApi(dom)}
          rows={ms.map((m) => (
            <tr key={m.api_id}>
              {all && <td className="v">{domName(m.domain)}</td>}
              <td style={{ fontSize: 12.5 }}>
                {m.api_name}
                <br />
                <span className={`mono ${styles.muted}`} style={{ fontSize: 10.5 }}>
                  {shortApi(m.api_id)}
                </span>
              </td>
              <td className="v">
                {m.kind === 'write' ? '쓰기' : '조회'} · {m.action}
              </td>
              <td className={styles.small}>
                {m.selectors == null ? (
                  <Muted />
                ) : !m.selectors.length ? (
                  <span className={styles.muted}>
                    없음{m.selectors_source === 'override' ? ' · 확인' : ''}
                  </span>
                ) : (
                  m.selectors.map((s) => (
                    <div key={s.field}>
                      <b className="mono" style={{ fontSize: 11 }}>
                        {s.field}
                      </b>
                      {!s.complete && (
                        <span className={styles.signal} style={{ fontSize: 11 }}>
                          {' '}
                          미완성
                        </span>
                      )}
                      <br />
                      {s.values.map((v) => (
                        <span
                          key={v.value}
                          className={`${styles.kchip} ${v.source === 'override' ? styles.man : ''}`}
                          title={v.aliases.length ? '다른 이름: ' + v.aliases.join(', ') : ''}
                        >
                          {v.value}
                          {v.name ? ' ' + v.name : ''}
                        </span>
                      ))}
                    </div>
                  ))
                )}
              </td>
              <td className={`v ${m.irreversible === '불가' ? styles.danger : ''}`}>{m.irreversible}</td>
              <td className={styles.small}>{m.memo ? m.memo : <Muted />}</td>
              <td className="v">v{m.metadata_version}</td>
            </tr>
          ))}
        />
        <Note>
          개발 담당자가 data/config/overrides.yaml 에서 보정한다 (
          <span className={`${styles.kchip} ${styles.man}`}>진한 칩</span> = 사람이 보정). 상태 그래프의
          화살표 API 는 이 값에서 자동으로 찾는다.
        </Note>
      </>
    ),
  };
}

export function toolDoc(a: AdminData, dom: string | null): DocResult {
  const ids = new Set(a.metaOf(dom).map((m) => m.api_id));
  const ts = a.env.tools.filter((t) => ids.has(t.api_id));
  const w = ts.filter((t) => t.approval_required).length;
  return {
    count: ts.length ? `도구 ${ts.length}개 · 쓰기 ${w} · 조회 ${ts.length - w}` : '',
    body: (
      <>
        <p className={styles.fixedrule}>
          <b>모든 도구에 고정</b>
          <span>쓰기 · 재시도 0 · 승인 필수</span>
          <span>조회 · 재시도 2 · 승인 불필요</span>
        </p>
        <Tbl
          head={['API', '도메인', 'timeout', '재시도', '승인', '인증', '성공 판단', '사용']}
          empty={noApi(dom)}
          rows={ts.map((t) => (
            <tr key={t.api_id}>
              <td className={styles.f}>{t.endpoint}</td>
              <td className="v">{domName(t.domain)}</td>
              <td className="v">{t.timeout_ms}ms</td>
              <td className="v">{t.retry_count}</td>
              <td className="v">{t.approval_required ? '필수' : '—'}</td>
              <td className="v" style={{ fontSize: 11 }}>
                {t.auth_type}
                {t.auth_profile ? ' · ' + t.auth_profile : ''}
              </td>
              <td className="v" style={{ fontSize: 11 }}>
                {t.success_rule ? (
                  `${t.success_rule.path} = ${t.success_rule.equals}`
                ) : (
                  <span className={styles.signal}>검수</span>
                )}
              </td>
              <td className="v">{t.enabled ? '사용' : <span className={styles.danger}>안 함</span>}</td>
            </tr>
          ))}
        />
        <Note>
          Hmall 은 실패해도 HTTP 200 이라 성공 판단은 응답 본문 규칙으로 한다. 실행기는 아직 구현 전.
        </Note>
      </>
    ),
  };
}

export function svDoc(a: AdminData, dom: string | null): DocResult {
  const gs = a.graphsIn(dom);
  const rows: ReactNode[] = [];
  gs.forEach((g) => {
    const codes = g.code_group?.codes ?? {};
    Object.entries(codes).forEach(([c, n]) => {
      const makes = g.transitions.filter((t) => String(t.to) === c);
      const lk = (g.lookups ?? []).find((l) => l.states.map(String).includes(c));
      const syn = [
        ...new Set(
          a.rules
            .filter((r) => r.doc === 'sv' && r.item === 'syn' && r.target === `${g.graph.id}:${c}`)
            .flatMap((r) =>
              String(r.body)
                .split(/[,·]/)
                .map((x) => x.trim())
                .filter(Boolean),
            ),
        ),
      ];
      rows.push(
        <tr key={`${g.graph.id}:${c}`}>
          <td className="v">{g.graph.name}</td>
          <td>{n}</td>
          <td className="v">{c}</td>
          <td className={styles.small}>{syn.length ? syn.join(', ') : <Muted />}</td>
          <td style={{ fontSize: 11.5 }}>
            {makes.length ? (
              makes.map((t, i) => (
                <span key={i}>
                  {i > 0 && <br />}
                  {t.name}{' '}
                  <span className={`mono ${styles.muted}`}>
                    {t.from}→{t.to}
                  </span>
                </span>
              ))
            ) : (
              <Muted />
            )}
          </td>
          <td className="v" style={{ fontSize: 11 }}>
            {lk ? `${shortApi(lk.api).split('/').pop()} ${selStr(lk.selector)}` : <Muted />}
          </td>
        </tr>,
      );
    });
  });
  const states = gs.reduce((n, g) => n + Object.keys(g.code_group?.codes ?? {}).length, 0);
  return {
    count: gs.length ? `그래프 ${gs.length}개 · 상태 ${states}개` : '',
    body: (
      <>
        <Tbl
          head={['그래프', '상태', '코드', '동의어', '만드는 동작', '조회 방법']}
          empty="이 도메인이 주인인 상태 그래프가 없습니다. 화살표에 붙는 API 는 어느 도메인 것이든 쓸 수 있습니다."
          rows={rows}
        />
        <Note>
          상태 · 코드는 공통코드, 동작 · 조회 방법은 소스 확인. 화면에서는 이 도메인의{' '}
          <b>상태 그래프 만들기</b>에서 편집한다. <b>동의어</b>는 도메인 › 규칙 입력 › State Vocabulary 에서
          넣고, 시나리오 생성 때 목표 추출(LLM)에 상태 목록과 함께 보여 준다.
        </Note>
      </>
    ),
  };
}
