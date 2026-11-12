import { useEffect, useState, type KeyboardEvent } from 'react';

import { useDeleteScenario, useEnvironment, useRegisteredScenarios } from '../../api/queries';
import { Card } from '../../components/Card';
import { Pill } from '../../components/Pill';
import { Spinner } from '../../components/Spinner';
import { domName } from '../../lib/format';
import { useStore } from '../../lib/store';
import { flow, forget, openSaved } from './flow';
import styles from './register.module.css';

/** 등록된 시나리오 — 행을 누르면 열어 보기(읽기 전용), 삭제는 두 번 눌러 확인 */
export function RegisteredList() {
  const list = useRegisteredScenarios();
  const env = useEnvironment();
  const remove = useDeleteScenario();
  const { viewingId } = useStore(flow);
  const [armed, setArmed] = useState<string | null>(null);

  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(null), 3000);
    return () => window.clearTimeout(timer);
  }, [armed]);

  const version = env.data?.build.catalog_version;
  const stale = (v: number | null | undefined) => v != null && version != null && v !== version;
  const rows = list.data ?? [];

  async function onDelete(id: string) {
    if (armed !== id) return setArmed(id);
    setArmed(null);
    try {
      await remove.mutateAsync(id);
      forget(id);
    } catch (error) {
      flow.set({ message: '삭제하지 못했어요: ' + (error as Error).message });
    }
  }

  const onKey = (event: KeyboardEvent<HTMLTableRowElement>, id: string) => {
    if ((event.key === 'Enter' || event.key === ' ') && event.target === event.currentTarget) {
      event.preventDefault();
      openSaved(id);
    }
  };

  return (
    <Card
      title={
        <>
          등록된 시나리오 <span className="cnt">({rows.length})</span>
        </>
      }
    >
      <div className="tbl-wrap">
        {list.isPending ? (
          <Spinner block label="등록된 시나리오 불러오는 중" />
        ) : list.isError ? (
          <p className="nodata">목록을 불러오지 못했어요: {list.error.message}</p>
        ) : (
          <table className={styles.list}>
            {rows.length ? (
              <>
                <thead>
                  <tr>
                    <th>순번</th>
                    <th>시나리오명</th>
                    <th>자연어 요청</th>
                    <th>도메인</th>
                    <th>단계</th>
                    <th>등록</th>
                    <th>상태</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s, i) => (
                    <tr
                      key={s.id}
                      className={`${styles.row} ${viewingId === s.id ? styles.cur : ''}`}
                      tabIndex={0}
                      aria-label={`${s.name} 보기`}
                      onClick={(e) => {
                        if (!(e.target as HTMLElement).closest('[data-acts]')) openSaved(s.id);
                      }}
                      onKeyDown={(e) => onKey(e, s.id)}
                    >
                      <td className="v">{i + 1}</td>
                      <td className={styles.name}>{s.name}</td>
                      <td className={styles.desc} title={s.utterance}>
                        {s.utterance}
                      </td>
                      <td>
                        {s.domains.map((d) => (
                          <span key={d} className="tag">
                            {domName(d)}
                          </span>
                        ))}
                      </td>
                      <td className="v">
                        {s.steps}
                        {s.irreversible > 0 && (
                          <>
                            {' '}
                            <span className={`${styles.badge} ${styles.warnB}`} title="되돌릴 수 없는 단계">
                              R2 {s.irreversible}
                            </span>
                          </>
                        )}
                      </td>
                      <td className="v">
                        {s.registered_at ?? ''}
                        <br />
                        <span className={styles.who}>{s.approver ?? ''}</span>
                      </td>
                      <td>
                        {stale(s.catalog_version) ? (
                          <Pill tone="signal">재승인 필요</Pill>
                        ) : (
                          <Pill tone="good">등록</Pill>
                        )}
                      </td>
                      <td className={styles.acts} data-acts>
                        <button
                          className={`xlink ${armed === s.id ? styles.armed : ''}`}
                          type="button"
                          onClick={() => onDelete(s.id)}
                        >
                          {armed === s.id ? '삭제 확인' : '삭제'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </>
            ) : (
              <tbody>
                <tr>
                  <td className="nodata">
                    등록된 시나리오가 없습니다. 아래에 자연어 요청을 입력하고 분석하세요.
                  </td>
                </tr>
              </tbody>
            )}
          </table>
        )}
      </div>
    </Card>
  );
}
