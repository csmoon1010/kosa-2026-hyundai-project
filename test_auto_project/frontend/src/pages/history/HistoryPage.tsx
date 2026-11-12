import { Fragment, type KeyboardEvent } from 'react';

import { useRuns } from '../../api/queries';
import { Card } from '../../components/Card';
import { Pill } from '../../components/Pill';
import { Spinner } from '../../components/Spinner';
import { useStore } from '../../lib/store';
import styles from './history.module.css';
import { historyFilter as filter } from './historyFilter';

/** 실행 이력 — 드라이런 · 실행 기록 (실행기 연결 전이라 지금은 드라이런만) */
export default function HistoryPage() {
  const { search, kind, open } = useStore(filter);
  const runs = useRuns();
  const all = runs.data ?? [];
  const q = search.trim();
  const shown = all.filter(
    (r) =>
      (!kind || r.kind === kind) &&
      (!q || r.rows.some((x) => (x.name ?? '').includes(q)) || r.id.includes(q)),
  );
  const toggle = (id: string) => filter.set((s) => ({ open: s.open === id ? null : id }));
  const onKey = (event: KeyboardEvent<HTMLTableRowElement>, id: string) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggle(id);
    }
  };

  return (
    <Card title="실행 이력">
      <div className="filters">
        <input
          type="search"
          placeholder="시나리오명 또는 추적 태그로 검색"
          aria-label="실행 이력 검색"
          value={search}
          onChange={(e) => filter.set({ search: e.target.value })}
        />
        <select aria-label="종류 필터" value={kind} onChange={(e) => filter.set({ kind: e.target.value })}>
          <option value="">종류 전체</option>
          <option value="드라이런">드라이런</option>
          <option value="실행">실행</option>
        </select>
      </div>
      {runs.isPending ? (
        <Spinner block label="실행 이력 불러오는 중" />
      ) : runs.isError ? (
        <p className="nodata">실행 이력을 불러오지 못했어요: {runs.error.message}</p>
      ) : (
        <>
          <p className="note">
            총 {all.length}건 · 드라이런 {all.filter((r) => r.kind === '드라이런').length} · 실행 0 (실행기
            연결 전)
          </p>
          <div style={{ marginTop: 13 }}>
            {shown.length ? (
              <div className="tbl-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>시각</th>
                      <th>시나리오</th>
                      <th>건수</th>
                      <th>호출</th>
                      <th>미해결</th>
                      <th>종류</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((r) => (
                      <Fragment key={r.id}>
                        <tr
                          className={`${styles.row} ${open === r.id ? styles.open : ''}`}
                          tabIndex={0}
                          aria-expanded={open === r.id}
                          onClick={() => toggle(r.id)}
                          onKeyDown={(e) => onKey(e, r.id)}
                        >
                          <td className="v">{r.at}</td>
                          <td className={styles.names}>
                            {r.rows.map((x) => x.name || x.scenario_id).join(', ')}
                          </td>
                          <td className="v">{r.rows.reduce((a, x) => a + (x.count ?? 0), 0)}</td>
                          <td className="v">{r.calls.length}</td>
                          <td className={`v ${r.unresolved.length ? styles.unresolved : ''}`}>
                            {r.unresolved.length}
                          </td>
                          <td>
                            <Pill tone="muted">{r.kind}</Pill>
                          </td>
                        </tr>
                        {open === r.id && (
                          <tr>
                            <td colSpan={6}>
                              <div className={styles.chips}>
                                {r.calls.map((c, i) => (
                                  <span key={i}>
                                    {c.scenario} #{c.k} {c.name}
                                  </span>
                                ))}
                              </div>
                              <p className={`note ${styles.rollback}`}>
                                되돌리는 순서:{' '}
                                {r.rollback.map((x) => `${x.name} → ${x.with || '없음'}`).join(' · ') || '—'}
                              </p>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="nodata">
                {all.length
                  ? '조건에 맞는 이력이 없습니다.'
                  : '실행 이력이 없습니다. 실행 메뉴에서 드라이런을 하면 여기에 남습니다.'}
              </p>
            )}
          </div>
        </>
      )}
    </Card>
  );
}
