import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router';

import { useHealth } from '../api/queries';
import { MENUS } from '../lib/menus';
import { usePreprocessingRefresh } from '../lib/usePreprocessingRefresh';
import styles from './Layout.module.css';
import { PageActionsSlot } from './pageActionsSlot';
import { Pill } from './Pill';

/** 지금 화면의 머리 오른쪽 배지 — 서버(FastAPI)와 연결됐는지, 가짜 LLM 으로 띄운 서버인지 */
function ServerBadge() {
  const health = useHealth();
  if (health.isPending) return null;
  if (!health.data?.ok)
    return (
      <Pill tone="danger" title={health.error?.message}>
        서버 없음
      </Pill>
    );
  return (
    <>
      {health.data.fake_llm && (
        <Pill tone="signal" title="tap.cli serve --fake-llm — 분석 · IR 생성 결과가 실제가 아닙니다">
          가짜 LLM
        </Pill>
      )}
      <Pill tone="good">서버 연결됨</Pill>
    </>
  );
}

export function Layout() {
  const { pathname } = useLocation();
  const menu = MENUS.find((m) => pathname === m.path || pathname.startsWith(m.path + '/'));
  const [actions, setActions] = useState<HTMLElement | null>(null);
  const prep = usePreprocessingRefresh();
  return (
    <div className={styles.shell}>
      <nav className={styles.side} aria-label="메뉴">
        <div className={styles.brand}>
          <span className={styles.logo} aria-hidden="true">
            T
          </span>
          <b>테스트 데이터 생성기</b>
        </div>
        <ul>
          {MENUS.map((m) => (
            <li key={m.path}>
              <NavLink to={m.path} className={styles.nav}>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  {m.icon}
                </svg>
                {m.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className={styles.app}>
        <header className={styles.head}>
          <h1>{menu?.label ?? '테스트 데이터 생성기'}</h1>
          <div className={styles.headRight}>
            <ServerBadge />
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              disabled={prep.busy}
              onClick={() => void prep.run()}
            >
              전처리 산출물 갱신
            </button>
            <span ref={setActions} className={styles.headRight} />
          </div>
        </header>
        <p className={styles.prepStatus} role="status" aria-live="polite" title={prep.title}>
          {prep.text}
        </p>
        <PageActionsSlot.Provider value={actions}>
          <Outlet />
        </PageActionsSlot.Provider>
      </main>
    </div>
  );
}
