import { useNavigate } from 'react-router';

import type { AdminData } from './adminData';
import { scopeSub } from './adminData';
import styles from './admin.module.css';
import { DOMAINS, type Scope } from './scope';

/** 관리자 메뉴 위쪽 — 전사 | 도메인 3개 (도메인 아래 작은 글씨: 그래프 · API 수) */
export function ScopeBar({ a, scope }: { a: AdminData | null; scope: Scope }) {
  const navigate = useNavigate();
  return (
    <div className={styles.scopebar} role="tablist" aria-label="관리 범위">
      <button
        type="button"
        role="tab"
        className={`${styles.scopebtn} ${styles.all}`}
        aria-selected={scope === 'all'}
        onClick={() => navigate('/admin/all')}
      >
        <span>전사</span>
        <i>공통 설정</i>
      </button>
      <span className={styles.sep} aria-hidden="true" />
      {DOMAINS.map(([d, n]) => (
        <button
          key={d}
          type="button"
          role="tab"
          className={styles.scopebtn}
          aria-selected={scope === d}
          onClick={() => navigate('/admin/' + d)}
        >
          <span>{n}</span>
          <i>{a ? scopeSub(a, d) : '…'}</i>
        </button>
      ))}
    </div>
  );
}
