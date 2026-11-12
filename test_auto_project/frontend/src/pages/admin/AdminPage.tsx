import { useParams } from 'react-router';

import { Pending } from '../Pending';

/** /admin/:scope — all(전사) 또는 도메인 코드 (지금 화면의 위쪽 범위 탭) */
export default function AdminPage() {
  const { scope = 'all' } = useParams();
  return <Pending phase={`R4. 관리자 — ${scope === 'all' ? '전사' : scope}`} />;
}
