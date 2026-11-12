import { Card } from '../../components/Card';
import { useStored } from '../../lib/storage';
import { useStore } from '../../lib/store';
import { Muted, WarnList } from './AnalysisCards';
import { approve, inspect, isError, setChecked } from './inspectState';
import styles from './inspect.module.css';
import { FINAL_TONE, NEED_TONE, pill } from './tones';

/** 승인 게이트 — 단계마다 권한 등급 · 등록 때 · 실행 때, 차단 목록, 단계 확인 → 승인 (승인본 고정) */
export function GateCard() {
  const s = useStore(inspect);
  const [approver, setApprover] = useStored('tdg.approver');
  const a = s.analysis;
  if (!a || isError(a)) return null;
  const g = a.gate;
  const open = g.status === '승인 필요' || g.status === '자동';
  const allChecked = g.need_steps.every((k) => s.checked[k]);
  const ap = s.approved;

  return (
    <Card className={styles.cardGap} title="승인 게이트 — 권한 등급" actions={pill(g.status, FINAL_TONE)}>
      {g.steps.length > 0 && (
        <div className="tbl-wrap">
          <table className={styles.steps}>
            <thead>
              <tr>
                <th>단계</th>
                <th>등급</th>
                <th>등록 때</th>
                <th>실행 때</th>
              </tr>
            </thead>
            <tbody>
              {g.steps.map((st) => (
                <tr key={st.key}>
                  <td className={styles.xs}>
                    <b>{st.key}</b> {st.edge}
                  </td>
                  <td className="v">{st.tier || '—'}</td>
                  <td>
                    {pill(st.requirement, NEED_TONE)}
                    <br />
                    <span className={`note ${styles.note0}`} style={{ fontSize: 11 }}>
                      {st.reasons.join(' · ')}
                    </span>
                  </td>
                  <td>{st.confirm_on_run ? pill('매번 확인', { '매번 확인': 'signal' }) : <Muted />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <WarnList items={g.blocked} title="차단 — 승인할 수 없음" />
      {open && g.status !== '자동' && (
        <>
          <p className="eyebrow" style={{ margin: '14px 0 4px' }}>
            등록 승인 — 계획이 맞는가 (승인본 고정)
          </p>
          {ap ? (
            <p className={styles.small} style={{ margin: '4px 0' }}>
              ✓ 승인 {ap.approval.approver} · {ap.approval.at} →{' '}
              <span className={`mono ${styles.code11}`}>{ap.file}</span>
            </p>
          ) : (
            <>
              <div>
                {g.need_steps.map((k) => (
                  <label key={k} className={styles.check}>
                    <input
                      type="checkbox"
                      checked={Boolean(s.checked[k])}
                      onChange={(e) => setChecked(k, e.target.checked)}
                    />{' '}
                    단계 {k} 의 API 가 맞는지 직접 확인했음
                  </label>
                ))}
                <label className={styles.approver}>
                  승인자
                  <input
                    type="text"
                    value={approver}
                    placeholder="이름"
                    onChange={(e) => setApprover(e.target.value)}
                  />
                </label>
              </div>
              <div className="btn-row" style={{ marginTop: 8 }}>
                <button
                  className="btn btn-primary"
                  type="button"
                  disabled={!allChecked || s.note?.kind === 'checking'}
                  onClick={() => void approve(approver.trim())}
                >
                  승인 (승인본 고정)
                </button>
              </div>
            </>
          )}
        </>
      )}
      <ApproveNote />
      <p className="note">R0 조회 · R1 되돌릴 수 있는 쓰기 · R2 되돌릴 수 없는 쓰기 · R3 범위 밖</p>
    </Card>
  );
}

function ApproveNote() {
  const { note } = useStore(inspect);
  if (!note) return null;
  if (note.kind === 'checking') return <p className="note">서버가 승인 확인 중…</p>;
  if (note.kind === 'offline') return <p className="note">서버에 연결하지 못했습니다: {note.error}</p>;
  if (note.kind === 'refused')
    return (
      <div className={styles.warn} role="alert">
        <b>✗ 승인 불가</b>
        <br />
        {note.error}
      </div>
    );
  return (
    <>
      <p className="note">승인본을 고정했어요.</p>
      {note.started ? (
        <p className="note">
          승인된 계획으로 <b>IR 초안 생성</b>을 시작했어요.
        </p>
      ) : (
        <div className={styles.warn}>{note.warn}</div>
      )}
    </>
  );
}
