import { useGraphReview } from '../../api/queries';
import { Card } from '../../components/Card';
import { Pill } from '../../components/Pill';
import { domName, shortApi } from '../../lib/format';
import type { AdminData } from './adminData';
import styles from './admin.module.css';
import { Kv, Tbl } from './parts';

const ITEM: Record<string, string> = {
  domain: '도메인 미분류',
  kind: '쓰기/조회 판별 불가',
  success_rule: '성공 판단 규칙 없음',
  enabled: '인증 비밀값 참조 없음',
  selectors: '구분값 목록 미완성',
};

/** 전사 — 1단계 산출물 · 검수 목록 (규칙으로 확정하지 못한 것 · 상태 그래프 검수) */
export function RealCard({ a }: { a: AdminData }) {
  const graphReview = useGraphReview();
  const b = a.build;
  const src = (b.spec_sources[0] ?? {}) as { document_id?: string; spec_hash?: string };
  const by: Record<string, number> = {};
  a.review.forEach((r) => (by[r.item] = (by[r.item] ?? 0) + 1));
  const gr = graphReview.data?.items ?? [];
  return (
    <Card
      className={styles.wide}
      title="1단계 산출물 · 검수 목록"
      actions={<span className={styles.ver}>catalog v{b.catalog_version}</span>}
    >
      <Kv
        items={[
          [
            '입력 명세',
            <span className="mono" key="s">
              {src.document_id ?? ''} · {(src.spec_hash ?? '').slice(7, 19)}
            </span>,
          ],
          ['API', `${b.operations}개 (쓰기 ${b.kinds.write || 0}개 · 조회 ${b.kinds.read || 0}개)`],
          [
            '도메인',
            Object.entries(b.domains)
              .map(([d, n]) => `${domName(d)} ${n}`)
              .join(' · '),
          ],
          [
            '생성 시각',
            <span className="mono" key="g">
              {a.env.generated_at}
            </span>,
          ],
        ]}
      />
      <p className="eyebrow" style={{ margin: '16px 0 7px' }}>
        검수 대기 {a.review.length}건 — 규칙으로 확정하지 못해 사람이 볼 것 ·{' '}
        {Object.entries(by)
          .map(([k, n]) => `${ITEM[k] ?? k} ${n}`)
          .join(' · ')}
      </p>
      <Tbl
        head={['API', '항목', '이유']}
        empty="검수할 것이 없습니다."
        rows={a.review.map((r, i) => (
          <tr key={i}>
            <td className={styles.f}>{shortApi(r.api_id)}</td>
            <td className="v">{ITEM[r.item] ?? r.item}</td>
            <td className={styles.small}>{r.reason}</td>
          </tr>
        ))}
      />
      <p className="note" style={{ marginTop: 10 }}>
        보정: 각 도메인 › 규칙 입력, 또는 data/config/overrides.yaml 에 적고{' '}
        <span className="mono">tap.cli build</span> 다시 실행
      </p>
      <p className="eyebrow" style={{ margin: '18px 0 7px' }}>
        상태 그래프 — 시나리오를 만들 때 API 를 못 찾을 것 같은 화살표 · 조회 {gr.length}건 (개발 담당자 검수)
      </p>
      <Tbl
        head={['그래프', '종류', '항목', '상태', '이유']}
        empty="검수할 것이 없습니다."
        rows={gr.map((x, i) => (
          <tr key={i}>
            <td className="v">{x.graph}</td>
            <td className="v">{x.kind}</td>
            <td style={{ fontSize: 12.5 }}>{x.item}</td>
            <td>
              <Pill tone={x.status === '없음' ? 'signal' : 'muted'}>
                {x.status === '없음' ? '못 찾음' : '애매'}
              </Pill>
            </td>
            <td style={{ fontSize: 11.5 }}>{x.why}</td>
          </tr>
        ))}
      />
      <p className="note" style={{ marginTop: 8 }}>
        API Metadata 에 별칭 · 구분값을 보정(각 도메인 › 규칙 입력 또는 overrides.yaml)하면 다시 찾습니다.
      </p>
    </Card>
  );
}
