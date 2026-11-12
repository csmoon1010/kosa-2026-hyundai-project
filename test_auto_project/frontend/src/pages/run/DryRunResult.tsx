import { useNavigate } from 'react-router';

import { Card } from '../../components/Card';
import { ParamTable } from '../../components/ParamTable';
import sc from '../../components/scenario.module.css';
import { apiCode } from '../../lib/format';
import styles from './run.module.css';
import type { Run } from './runState';

type Call = Run['calls'][number];

/** 드라이런 결과 — 시나리오(반복이면 #k)마다 단계 카드 · 입력값 표 · 보낼 요청 XML */
export function DryRunResult({ run }: { run: Run }) {
  const navigate = useNavigate();
  const groups: { k: string; title: string; calls: Call[] }[] = [];
  run.calls.forEach((c) => {
    const k = `${c.scenario_id}#${c.k}`;
    let g = groups.find((x) => x.k === k);
    if (!g) {
      const count = run.rows.find((r) => r.scenario_id === c.scenario_id)?.count ?? 1;
      g = { k, title: `${c.scenario ?? ''}${count > 1 ? ` #${c.k}` : ''}`, calls: [] };
      groups.push(g);
    }
    g.calls.push(c);
  });

  return (
    <Card
      className={`fade ${styles.result}`}
      title="드라이런 결과"
      actions={<span className={sc.sum}>요청 {run.calls.length}건 · 실제 API 는 호출하지 않았어요</span>}
    >
      {groups.map((g) => (
        <section key={g.k} className={sc.task}>
          <div className={sc.taskHead}>
            <b>{g.title}</b>
          </div>
          <ol className={sc.steps}>
            {g.calls.map((c, i) => (
              <li key={`${c.step_id}-${i}`} className={sc.step}>
                <span className={sc.kind}>
                  <b>{i + 1}</b>
                </span>
                <div>
                  <div className={sc.edge}>{c.name ?? ''}</div>
                  <span className={`${sc.api} mono`}>{apiCode(c.api_id ?? '')}</span>
                  <ParamTable apiId={c.api_id ?? ''} inputs={c.inputs} bindings={c.bindings} />
                  {c.xml && (
                    <details className={sc.memo}>
                      <summary>보낼 요청 XML</summary>
                      <pre className={styles.xml}>{c.xml}</pre>
                    </details>
                  )}
                </div>
                <div className={sc.badges}>
                  {c.tier === 'R2' && <span className={`${sc.badge} ${sc.warnB}`}>되돌릴 수 없음</span>}
                </div>
              </li>
            ))}
          </ol>
        </section>
      ))}
      {run.unresolved.length > 0 && (
        <details className={sc.memo}>
          <summary>메모 {run.unresolved.length}개</summary>
          <ul>
            {run.unresolved.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </details>
      )}
      <p className={sc.done}>✓ 실행 이력에 남겼어요</p>
      <div className="btn-row">
        <button className="btn btn-ghost btn-sm" type="button" onClick={() => navigate('/history')}>
          실행 이력 보기
        </button>
      </div>
    </Card>
  );
}
