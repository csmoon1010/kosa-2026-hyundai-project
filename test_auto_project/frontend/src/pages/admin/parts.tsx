import type { ReactNode } from 'react';

import styles from './admin.module.css';

/** 표 — 행이 없으면 안내 한 줄 (지금 화면의 tbl) */
export function Tbl({ head, rows, empty }: { head: string[]; rows: ReactNode[]; empty: string }) {
  if (!rows.length) return <p className="nodata">{empty}</p>;
  return (
    <div className="tbl-wrap">
      <table>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  );
}

export const Muted = () => <span className={styles.muted}>—</span>;

/** 이름 · 값 목록 (지금 화면의 .kv) */
export function Kv({ items }: { items: [string, ReactNode][] }) {
  return (
    <ul className={styles.kv}>
      {items.map(([k, v]) => (
        <li key={k}>
          <span className={styles.k}>{k}</span>
          <span>{v}</span>
        </li>
      ))}
    </ul>
  );
}

export type Check = [boolean, string];

/** 저장 시점 검증 — OK / ✕ 목록, 거부면 빨간 상자 */
export function Checks({
  checks,
  reject,
}: {
  checks: Check[];
  reject?: { title: string; text: string } | null;
}) {
  return (
    <div>
      <p className="eyebrow" style={{ margin: '10px 0 6px' }}>
        저장 시점 검증
      </p>
      <ul className={styles.checks}>
        {checks.map(([ok, text], i) => (
          <li key={i} className={ok ? '' : styles.bad}>
            <span className={ok ? styles.pass : styles.fail}>{ok ? 'OK' : '✕'}</span>
            <span>{text}</span>
          </li>
        ))}
      </ul>
      {reject && (
        <div className={styles.dangerBox} role="alert">
          <b>{reject.title}</b>
          {reject.text}
        </div>
      )}
    </div>
  );
}
