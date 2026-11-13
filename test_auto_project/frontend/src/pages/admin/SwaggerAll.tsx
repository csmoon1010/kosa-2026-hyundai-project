import { useState } from 'react';

import { post, type Schemas } from '../../api/client';
import { useRefreshAdmin } from '../../api/queries';
import { Card } from '../../components/Card';
import { Pill } from '../../components/Pill';
import { domName } from '../../lib/format';
import { useToast } from '../../lib/useToast';
import type { AdminData } from './adminData';
import styles from './admin.module.css';

type BuildResult = { build: Schemas['BuildInfo']; changed: boolean };

/** 전사 — Swagger 명세 소스 (도메인별 연결 설정) · 전체 변경 확인 = 다시 빌드 */
export function SwaggerAll({ a }: { a: AdminData }) {
  const refresh = useRefreshAdmin();
  const [busy, setBusy] = useState(false);
  const [toast, show] = useToast();
  const src = (a.build.spec_sources[0] ?? {}) as { document_id?: string };
  const cnt: Record<string, number> = {};
  a.meta.forEach((m) => (cnt[m.domain] = (cnt[m.domain] ?? 0) + 1));
  const off: Record<string, number> = {};
  a.env.tools.forEach((t) => {
    if (!t.enabled) off[t.domain] = (off[t.domain] ?? 0) + 1;
  });

  async function poll() {
    setBusy(true);
    try {
      const j = await post<BuildResult>('/api/admin/build');
      await refresh();
      show(
        j.changed
          ? `다시 빌드 — catalog v${j.build.catalog_version} 로 바뀌었습니다.`
          : `바뀐 것 없음 — catalog v${j.build.catalog_version}.`,
      );
    } catch (e) {
      show('빌드 실패: ' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      className={styles.wide}
      title="Swagger 명세 소스"
      actions={
        <button className="btn btn-ghost btn-sm" type="button" disabled={busy} onClick={() => void poll()}>
          전체 변경 확인
        </button>
      }
    >
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              {['도메인', '서비스', '명세 파일', 'API', 'base URL', 'timeout', '인증', '상태'].map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {a.env.connections.map((c) => (
              <tr key={`${c.service}-${c.domain}`}>
                <td className="v">
                  {domName(c.domain)} <span className={`mono ${styles.muted}`}>{c.domain}</span>
                </td>
                <td className="v">{c.service}</td>
                <td className={styles.f} style={{ fontSize: 10.5 }}>
                  data/specs/{src.document_id ?? ''}
                </td>
                <td className="v">{cnt[c.domain] ?? 0}개</td>
                <td className="v" style={{ fontSize: 11 }}>
                  {c.base_url}
                </td>
                <td className="v">{c.timeout_ms}ms</td>
                <td className="v" style={{ fontSize: 11 }}>
                  {c.auth_type}
                  {c.auth_profile ? ' · ' + c.auth_profile : ''}
                </td>
                <td>
                  {off[c.domain] ? (
                    <Pill tone="signal">사용 안 함 {off[c.domain]}</Pill>
                  ) : (
                    <Pill tone="good">정상</Pill>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note" style={{ marginTop: 12 }}>
        명세는 <span className="mono">data/specs/</span> 에 두고, 도메인별 연결 설정(base URL 환경변수 ·
        timeout · 인증 이름)은 <span className="mono">data/config/services.yaml</span> 에 적습니다. 인증
        비밀값은 설정 파일이 아니라 .env 에 둡니다. 바꾼 뒤 <b>전체 변경 확인</b>을 누르면 다시 빌드합니다.
      </p>
      <p className="toast" role="status" hidden={!toast}>
        {toast}
      </p>
    </Card>
  );
}
