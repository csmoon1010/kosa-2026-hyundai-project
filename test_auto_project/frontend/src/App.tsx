import { Navigate, Route, Routes } from 'react-router';

import { Layout } from './components/Layout';
import AdminPage from './pages/admin/AdminPage';
import HistoryPage from './pages/history/HistoryPage';
import InspectPage from './pages/inspect/InspectPage';
import RegisterPage from './pages/register/RegisterPage';
import RunPage from './pages/run/RunPage';

/** 메뉴마다 주소 — 새로고침 · 링크 공유 (docs/react.md 2절) */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/register" replace />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="inspect" element={<InspectPage />} />
        <Route path="run" element={<RunPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="admin" element={<Navigate to="/admin/all" replace />} />
        <Route path="admin/:scope" element={<AdminPage />} />
        <Route path="*" element={<Navigate to="/register" replace />} />
      </Route>
    </Routes>
  );
}
