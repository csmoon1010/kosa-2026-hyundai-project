import { NavLink, Outlet, useLocation } from 'react-router';

import { useHealth } from '../api/queries';
import { MENUS } from '../lib/menus';
import styles from './Layout.module.css';
import { Pill } from './Pill';

/** 지금 화면의 머리 오른쪽 배지 — 서버(FastAPI)와 연결됐는지 */
function ServerBadge() {
  const health = useHealth();
  if (health.isPending) return null;
  return health.data?.ok ? (
    <Pill tone="good">서버 연결됨</Pill>
  ) : (
    <Pill tone="danger" title={health.error?.message}>
      서버 없음
    </Pill>
  );
}

export function Layout() {
  const { pathname } = useLocation();
  const menu = MENUS.find((m) => pathname === m.path || pathname.startsWith(m.path + '/'));
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
          </div>
        </header>
        <Outlet />
      </main>
    </div>
  );
}
