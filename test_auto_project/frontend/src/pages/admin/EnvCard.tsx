import { Card } from '../../components/Card';
import type { AdminData } from './adminData';
import styles from './admin.module.css';
import { Kv } from './parts';

/** 전사 — 환경과 감사 (허용 환경 · base URL · 승인 게이트 · 실행기) */
export function EnvCard({ a }: { a: AdminData }) {
  const envs = [...new Set(a.env.connections.flatMap((c) => c.allowed_environments))];
  const w = a.env.tools.filter((t) => t.approval_required).length;
  return (
    <Card title="환경과 감사">
      <Kv
        items={[
          [
            '허용 환경',
            <span className="mono" key="e">
              {envs.join(' · ') || 'DEV'} — services.yaml
            </span>,
          ],
          [
            'base URL',
            <span className="mono" key="b">
              {[...new Set(a.env.connections.map((c) => c.base_url))].join(' · ')} (.env)
            </span>,
          ],
          [
            '승인 게이트',
            <span key="g">
              <span className={styles.dot} />
              쓰기 API {w}개 모두 승인 필수 · 재시도 0 (고정 규칙)
            </span>,
          ],
          ['실행기', '구현 전 — API 호출 없음 (드라이런만)'],
        ]}
      />
      <div className="btn-row">
        <button
          className="btn btn-ghost btn-sm"
          type="button"
          disabled
          title="실행기 구현 전이라 정리할 테스트 데이터가 없습니다"
        >
          테스트 데이터 전체 정리
        </button>
      </div>
    </Card>
  );
}
