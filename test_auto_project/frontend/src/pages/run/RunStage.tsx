import { useState } from 'react';

import type { Schemas } from '../../api/client';
import { useIsStale, useRefreshRuns, useRegisteredScenarios } from '../../api/queries';
import { Card } from '../../components/Card';
import { Pill } from '../../components/Pill';
import sc from '../../components/scenario.module.css';
import { useStore } from '../../lib/store';
import { DryRunResult } from './DryRunResult';
import styles from './run.module.css';
import { dryRun, isReady, needsConfirm, remove, runState, setConfirm, setRepeat } from './runState';

/** 오른쪽 — 선택된 시나리오 · 반복 · 이번 실행 확인 · 드라이런, 그 아래 결과 */
export function RunStage() {
  const s = useStore(runState);
  const registered = useRegisteredScenarios();
  const isStale = useIsStale();
  const refreshRuns = useRefreshRuns();
  const all = registered.data ?? [];
  const regOf = (id: string) => all.find((x) => x.id === id);
  const ready = isReady(s, regOf, isStale);
  const confirmRows = s.rows.filter((r) => needsConfirm(regOf(r.id)));

  async function onDryRun() {
    if (!ready) return;
    if (await dryRun(regOf)) await refreshRuns();
  }

  return (
    <>
      <Card
        title={
          <>
            선택된 시나리오 <span className="cnt">({s.rows.length})</span>
          </>
        }
      >
        {s.rows.length ? (
          <>
            <div className="tbl-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>시나리오</th>
                    <th>단계</th>
                    <th>반복</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {s.rows.map((r, i) => {
                    const reg = regOf(r.id);
                    return (
                      <tr key={r.key}>
                        <td className="v">{i + 1}</td>
                        <td className={styles.name}>
                          {reg ? reg.name : '삭제된 시나리오'}
                          {reg && isStale(reg) && (
                            <>
                              {' '}
                              <Pill tone="signal">재승인 필요</Pill>
                            </>
                          )}
                        </td>
                        <td className="v">
                          {reg ? reg.steps : '—'}
                          {reg && reg.irreversible > 0 && (
                            <>
                              {' '}
                              <span className={`${sc.badge} ${sc.warnB}`}>R2 {reg.irreversible}</span>
                            </>
                          )}
                        </td>
                        <td>
                          <RepeatInput row={r.key} value={r.n} />
                        </td>
                        <td className={styles.acts}>
                          <button className="xlink" type="button" onClick={() => remove(r.key)}>
                            빼기
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {confirmRows.length > 0 && (
              <div className={sc.approve}>
                <h3>
                  이번 실행에서 확인 <span className="cnt">{confirmRows.length}</span>
                </h3>
                <ul className={sc.checks}>
                  {confirmRows.map((r) => {
                    const reg = regOf(r.id) as Schemas['RegisteredSummary'];
                    return (
                      <li key={r.key}>
                        <label>
                          <input
                            type="checkbox"
                            checked={Boolean(s.confirm[r.key])}
                            onChange={(e) => setConfirm(r.key, e.target.checked)}
                          />{' '}
                          <b>{reg.name}</b> 되돌릴 수 없는 단계를 실행해도 돼요
                        </label>
                        <span className={sc.why}>
                          {reg.confirm_steps.map((c) => c.edge || c.key).join(' · ')}
                        </span>
                      </li>
                    );
                  })}
                </ul>
                <p className={sc.why}>되돌릴 수 없는 단계는 승인과 별개로 실행할 때마다 확인해요.</p>
              </div>
            )}
            <div className="btn-row">
              <button
                className="btn btn-primary"
                type="button"
                disabled={!ready || s.busy}
                onClick={() => void onDryRun()}
              >
                {s.busy ? '만드는 중…' : '드라이런'}
              </button>
              <button
                className="btn btn-ghost"
                type="button"
                disabled
                title="실행기 · 개발 서버 인증 연결 전"
              >
                실행 (연결 전)
              </button>
            </div>
            {s.error && <p className={sc.err}>{s.error}</p>}
          </>
        ) : (
          <p className="nodata">
            왼쪽에서 시나리오를 누르면 담깁니다.
            {all.length || registered.isPending ? '' : ' 아직 등록된 시나리오가 없습니다.'}
          </p>
        )}
      </Card>
      {s.result && <DryRunResult run={s.result} />}
    </>
  );
}

/** 반복 횟수 — 입력을 마치면(칸을 떠나거나 Enter) 1 ~ 20 으로 맞춘다 */
function RepeatInput({ row, value }: { row: string; value: number }) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    setRepeat(row, draft);
    setDraft(null);
  };
  return (
    <input
      type="text"
      inputMode="numeric"
      className={styles.repeat}
      aria-label="반복 횟수"
      value={draft ?? String(value)}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit();
      }}
    />
  );
}
