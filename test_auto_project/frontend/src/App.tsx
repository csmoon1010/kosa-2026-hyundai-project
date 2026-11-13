import { lazy, Suspense, type ReactNode } from 'react';
import { Navigate, Route, Routes } from 'react-router';

import { Layout } from './components/Layout';
import { Spinner } from './components/Spinner';
import HistoryPage from './pages/history/HistoryPage';
import RegisterPage from './pages/register/RegisterPage';
import RunPage from './pages/run/RunPage';

// 관리자(그래프 편집기 · React Flow) · 확인용 화면은 그 메뉴를 열 때 불러온다 — 첫 화면을 가볍게
const AdminPage = lazy(() => import('./pages/admin/AdminPage'));
const InspectPage = lazy(() => import('./pages/inspect/InspectPage'));
const page = (el: ReactNode) => (
  <Suspense fallback={<Spinner block label="화면 불러오는 중" />}>{el}</Suspense>
);

/** 메뉴마다 주소 — 새로고침 · 링크 공유 (docs/react.md 2절) */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/register" replace />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="inspect" element={page(<InspectPage />)} />
        <Route path="run" element={<RunPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="admin" element={<Navigate to="/admin/all" replace />} />
        <Route path="admin/:scope" element={page(<AdminPage />)} />
        <Route path="*" element={<Navigate to="/register" replace />} />
      </Route>
    </Routes>
  );
}
