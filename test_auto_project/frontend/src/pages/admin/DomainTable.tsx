import { useNavigate } from 'react-router';

import { Card } from '../../components/Card';
import { domName } from '../../lib/format';
import type { AdminData, Graph, Meta } from './adminData';
import styles from './admin.module.css';
import { DOMAINS, REAL_DOM } from './scope';

/** 전사 — 도메인별 추출 결과 (API · 그래프 · 전이 · 구분값 · 검수 · Baseline · 화면 규칙) */
export function DomainTable({ a }: { a: AdminData }) {
  const navigate = useNavigate();
  const row = (label: string, dom: string | null, apis: Meta[], gs: Graph[]) => {
    const w = apis.filter((m) => m.kind === 'write').length;
    const ids = new Set(apis.map((m) => m.api_id));
    return (
      <tr key={label}>
        <td className={styles.f}>
          {dom ? (
            <button type="button" className={styles.sbtn} onClick={() => navigate('/admin/' + dom)}>
              {label}
            </button>
          ) : (
            label
          )}
        </td>
        <td className="v">
          {apis.length}{' '}
          <span className={styles.muted}>
            (쓰기 {w} · 조회 {apis.length - w})
          </span>
        </td>
        <td className="v">{gs.length ? gs.map((g) => g.graph.name).join(', ') : '—'}</td>
        <td className="v">{gs.reduce((n, g) => n + g.transitions.length, 0) || '—'}</td>
        <td className="v">{apis.filter((m) => (m.selectors ?? []).length).length || '—'}</td>
        <td className="v">{a.review.filter((r) => ids.has(r.api_id)).length || '—'}</td>
        <td className="v">
          {apis.filter((m) => a.baselines[m.api_id]).length} / {apis.length}
        </td>
        <td className="v">{dom ? a.rules.filter((r) => r.dom === dom).length || '—' : '—'}</td>
      </tr>
    );
  };
  const own = new Set(Object.values(REAL_DOM));
  const rest = a.meta.filter((m) => !own.has(m.domain));
  return (
    <Card
      className={styles.wide}
      title="도메인별 추출 결과"
      actions={
        <span className={styles.ver}>
          catalog v<b>{a.build.catalog_version}</b>
        </span>
      }
    >
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              {[
                '도메인',
                '분류된 API',
                '상태 그래프',
                '전이',
                '구분값 있는 API',
                '검수 대기',
                'Baseline',
                '화면 규칙',
              ].map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DOMAINS.map(([d, n, code]) => row(`${n} · ${code}`, d, a.metaOf(d), a.graphsOf(d)))}
            {rest.length > 0 &&
              row(`그 밖 (${[...new Set(rest.map((m) => domName(m.domain)))].join(' · ')})`, null, rest, [])}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
