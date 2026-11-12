import type { Schemas } from '../../api/client';
import { useGraphs } from '../../api/queries';
import { Card } from '../../components/Card';
import { shortApi } from '../../lib/format';
import { JsonDetails } from './JsonDetails';
import type { Analysis, AnalysisError } from './inspectState';
import styles from './inspect.module.css';
import { FINAL_TONE, SEL_TONE, msTxt, pill } from './tones';

type Trace = Schemas['Trace'];
type Step = Schemas['Step'];

const usd = (v: number | null | undefined) => (v == null ? '가격 미설정' : `$${v.toFixed(4)}`);
export const Muted = () => <span className={styles.muted}>—</span>;
const selStr = (sel: Record<string, string> | null | undefined) =>
  Object.entries(sel ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .join(', ');

/** 단계 머리의 시간 · LLM 호출 · 토큰 */
function StageMeta({ trace, name }: { trace: Trace; name: string }) {
  const s = trace.spans.find((x) => x.name === name) ?? { ms: 0, llm_calls: 0 };
  const cs = trace.calls.filter((c) => c.stage[0] === name[0]);
  const tin = cs.reduce((a, c) => a + (c.input_tokens || 0), 0);
  const tout = cs.reduce((a, c) => a + (c.output_tokens || 0), 0);
  return (
    <span className={`note ${styles.note0}`}>
      {msTxt(s.ms)} · LLM {s.llm_calls}회{cs.length ? ` · 토큰 ${tin}+${tout}` : ''}
    </span>
  );
}

type Item = string | { path_sequence?: number | null; step?: number | null; reason: string };

/** 노란 상자 목록 — 지시문 · 애매한 부분 · 확인할 것 · 차단 */
export function WarnList({ items, title }: { items: Item[] | undefined; title: string }) {
  if (!items?.length) return null;
  return (
    <div className={styles.warn}>
      <b>{title}</b>
      {items.map((x, i) => (
        <span key={i}>
          <br />
          {typeof x === 'string'
            ? x
            : (x.path_sequence ? `${x.path_sequence}번 업무${x.step != null ? `-${x.step}` : ''}: ` : '') +
              x.reason}
        </span>
      ))}
    </div>
  );
}

const chain = (steps: Step[]) =>
  steps.length ? [steps[0]!.from, ...steps.map((x) => x.to)].join(' → ') : '(이동 없음)';

function CardHead({ title, trace, stage }: { title: string; trace: Trace; stage: string }) {
  return (
    <div
      className="card-hd-row"
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        gap: 10,
        flexWrap: 'wrap',
        marginBottom: 12,
      }}
    >
      <h2 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>{title}</h2>
      <StageMeta trace={trace} name={stage} />
    </div>
  );
}

/** 오른쪽 — 3단계 분석 결과 (요약 · ① 업무 · ② 경로 · ③ API). 분석이 멈췄으면 멈춤 카드 */
export function AnalysisCards({ a }: { a: Analysis | AnalysisError }) {
  const graphs = useGraphs();
  if ('error' in a && typeof a.error === 'string') {
    const err = a as AnalysisError;
    return (
      <Card className="fade" title="3단계 분석 — 멈춤">
        <div className={styles.warn}>
          <b>{err.error}</b>
        </div>
        {err.trace && (
          <p className="note">
            트레이스: {err.trace.status} · LLM {err.trace.totals.llm_calls}회 · {msTxt(err.trace.totals.ms)}
          </p>
        )}
      </Card>
    );
  }
  const r = a as Analysis;
  const t = r.trace.totals;
  const graphName = (id: string) => {
    const all = [...(graphs.data?.drafts ?? []), ...(graphs.data?.graphs ?? [])];
    return all.find((g) => g.graph.id === id)?.graph.name ?? id;
  };

  return (
    <>
      <Card
        className="fade"
        title="3단계 에이전트 결과"
        actions={
          <span>
            {pill(r.apis.status, FINAL_TONE)} 승인 게이트 {pill(r.gate.status, FINAL_TONE)}
          </span>
        }
      >
        <p className={`note ${styles.note0}`}>
          중지조건 · 재시도 {r.stopRetry === false ? <b>끔</b> : '켬'} · 전체 {msTxt(t.ms)} · LLM{' '}
          {t.llm_calls}회 ({msTxt(t.llm_ms)}) · 토큰 {t.input_tokens}+{t.output_tokens} · 비용{' '}
          {usd(t.cost_usd)} · <span className={`mono ${styles.code11}`}>{r.trace_file}</span>
        </p>
      </Card>

      <Card className={`fade ${styles.cardGap}`}>
        <CardHead title="① 자연어 업무 의도 분석" trace={r.trace} stage="① 의도 분석" />
        {r.tasks.tasks.length ? (
          <div className="tbl-wrap">
            <table className={styles.steps}>
              <thead>
                <tr>
                  <th>#</th>
                  <th>도메인</th>
                  <th>신규/기존</th>
                  <th>업무 · 조건</th>
                  <th>제약</th>
                  <th>건수</th>
                  <th>앞 업무</th>
                </tr>
              </thead>
              <tbody>
                {r.tasks.tasks.map((x) => (
                  <tr key={x.sequence}>
                    <td className="v">{x.sequence}</td>
                    <td className="v">{x.domain}</td>
                    <td className="v">{x.origin}</td>
                    <td className={styles.small}>
                      <b>{x.action}</b>
                      <br />
                      <span className={`note ${styles.note0}`}>{x.conditions}</span>
                    </td>
                    <td>
                      <div className={styles.chips}>
                        {x.constraints.length ? (
                          x.constraints.map((c, i) => (
                            <span key={i} title={c.source_phrase}>
                              {c.role} {c.name}={c.value}
                            </span>
                          ))
                        ) : (
                          <Muted />
                        )}
                      </div>
                    </td>
                    <td className="v">{x.count}</td>
                    <td className="v">{x.depends_on.length ? x.depends_on.join(', ') : <Muted />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="note">테스트 데이터를 만들거나 바꾸는 요청이 아니라 업무가 없습니다.</p>
        )}
        <WarnList
          items={r.tasks.injections}
          title="요청 속 지시문 — 감지되어 요청 전체를 차단했어요 (② ③ 을 하지 않음)"
        />
        <WarnList items={r.tasks.unresolved} title="업무로 만들지 않은 것 (애매한 부분)" />
        <JsonDetails label="① 의도 분석" value={r.tasks} />
      </Card>

      <Card className={`fade ${styles.cardGap}`}>
        <CardHead title="② Graph 경로 탐색" trace={r.trace} stage="② 경로 탐색" />
        {r.apis.status === '차단' && !r.paths.paths.length && (
          <p className="note">요청 속 지시문이 감지되어 ② 경로 탐색 · ③ API 선택을 하지 않았어요.</p>
        )}
        {r.paths.paths.length ? (
          r.paths.paths.map((p) => (
            <div key={p.sequence} className={styles.path}>
              <div className={styles.pathHead}>
                <b>{p.sequence}번 업무</b>
                <span className="tag">{p.domain}</span>
                <span className={styles.small}>
                  {p.graph_id ? (
                    <>
                      {graphName(p.graph_id)}{' '}
                      <span className={`mono ${styles.muted}`} style={{ fontSize: 10.5 }}>
                        {p.graph_id}
                      </span>
                    </>
                  ) : (
                    '상태 그래프 없음'
                  )}
                </span>
                {pill(p.status === 'ok' ? '경로 있음' : p.status, {
                  '경로 있음': 'good',
                  '경로 없음': 'signal',
                  '그래프 없음': 'muted',
                })}
              </div>
              {p.graph_id && (
                <>
                  <div style={{ fontSize: 13, marginTop: 6 }}>
                    <span className={styles.statePill}>{p.from_state || '—'}</span>{' '}
                    <span className={`note ${styles.note0}`}>{p.start_by || ''}</span> →{' '}
                    <span className={styles.statePill}>{p.to_state || '목표 없음'}</span>
                    {p.must_pass.length > 0 && (
                      <span className={`note ${styles.note0}`}> {p.must_pass.join(', ')} 거쳐서</span>
                    )}
                  </div>
                  {p.to_state_reason && (
                    <p className="note" style={{ margin: '4px 0 0' }}>
                      목표 근거: {p.to_state_reason}
                    </p>
                  )}
                  {p.steps.length > 0 && (
                    <p className={styles.small} style={{ margin: '6px 0 0' }}>
                      경로: {chain(p.steps)}{' '}
                      <span className={`note ${styles.note0}`}>
                        · 화살표 {p.steps.map((x) => x.edge).join(', ')}
                      </span>
                    </p>
                  )}
                  {p.alternatives.map((x, i) => (
                    <p key={i} className="note" style={{ margin: '4px 0 0' }}>
                      대안: {x.from_state}({x.start_by}) — {x.steps.length ? chain(x.steps) : '그대로 씀'} ·{' '}
                      {x.why}
                    </p>
                  ))}
                </>
              )}
              <WarnList items={p.notes} title="알릴 것" />
            </div>
          ))
        ) : (
          <p className="note">경로를 찾을 업무가 없습니다.</p>
        )}
        <JsonDetails label="② 경로 탐색" value={r.paths} />
      </Card>

      <Card className={`fade ${styles.cardGap}`}>
        <CardHead title="③ API 선택" trace={r.trace} stage="③ API 선택" />
        {r.apis.api_selection_results.length ? (
          <div className="tbl-wrap">
            <table className={styles.steps}>
              <thead>
                <tr>
                  <th>단계</th>
                  <th>종류</th>
                  <th>화살표 · 단계</th>
                  <th>고른 API · 구분값</th>
                  <th>선택</th>
                  <th>이유 · 후보</th>
                </tr>
              </thead>
              <tbody>
                {r.apis.api_selection_results.map((row) => (
                  <tr key={`${row.path_sequence}-${row.step}`}>
                    <td className="v">
                      {row.path_sequence}-{row.step}
                    </td>
                    <td className="v">{row.kind}</td>
                    <td className={styles.small}>
                      {row.edge}
                      {row.from && (
                        <>
                          <br />
                          <span className={`note ${styles.note0}`}>
                            {row.from} → {row.to}
                          </span>
                        </>
                      )}
                    </td>
                    <td className={styles.xs}>
                      {row.selected ? (
                        <>
                          <span className={`mono ${styles.code11}`}>
                            {shortApi(row.selected.api_id).split('/').pop()}
                          </span>
                          <br />
                          {selStr(row.selected.selector) || <Muted />}
                        </>
                      ) : (
                        <Muted />
                      )}
                    </td>
                    <td>
                      {pill(row.selection_status, SEL_TONE)}
                      <br />
                      <span className={`note ${styles.note0}`}>{row.selected_by || ''}</span>
                    </td>
                    <td className={styles.xs}>
                      {row.selection_reason}
                      <details className={styles.candidates} style={{ marginTop: 4 }}>
                        <summary>후보 {row.api_candidates.length}개</summary>
                        {row.api_candidates.map((c, i) => (
                          <div key={i} style={{ fontSize: 11 }}>
                            {shortApi(c.api_id).split('/').pop()} {selStr(c.selector)} · {c.score} · {c.check}
                            {c.check_reason ? ` (${c.check_reason})` : ''}
                          </div>
                        ))}
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="note">고를 단계가 없습니다.</p>
        )}
        <WarnList items={r.apis.unresolved} title="확인할 것" />
        <p className="note">가선택 = 사람 확인 필요 · 보류 = 고를 API 없음</p>
        <JsonDetails label="③ API 선택" value={r.apis} />
      </Card>
    </>
  );
}
