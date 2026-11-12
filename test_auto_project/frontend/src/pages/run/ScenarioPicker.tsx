import { useIsStale, useRegisteredScenarios } from '../../api/queries';
import { Card } from '../../components/Card';
import { Spinner } from '../../components/Spinner';
import { useStore } from '../../lib/store';
import styles from './run.module.css';
import { pick, runState } from './runState';

/** 왼쪽 — 등록 시나리오 검색 · 누르면 담긴다. 재승인 필요는 담지 못한다 */
export function ScenarioPicker() {
  const { search } = useStore(runState);
  const registered = useRegisteredScenarios();
  const isStale = useIsStale();
  const all = registered.data ?? [];
  const q = search.trim();
  const list = all.filter((s) => !q || s.name.includes(q) || s.utterance.includes(q));

  return (
    <Card title="시나리오 선택">
      <div className={styles.search}>
        <input
          type="search"
          placeholder="시나리오 검색"
          aria-label="실행 시나리오 검색"
          value={search}
          onChange={(e) => runState.set({ search: e.target.value })}
        />
      </div>
      {registered.isPending ? (
        <Spinner block label="등록된 시나리오 불러오는 중" />
      ) : (
        <ul className={styles.list}>
          {list.length ? (
            list.map((s) => (
              <li key={s.id}>
                <button
                  className={styles.item}
                  type="button"
                  disabled={isStale(s)}
                  onClick={() => pick(s.id)}
                >
                  <b>{s.name}</b>
                  <span className={styles.itemNote}>
                    단계 {s.steps}
                    {s.irreversible ? ` · 되돌릴 수 없는 단계 ${s.irreversible}` : ''}
                    {isStale(s) && <span className={styles.restale}> · 재승인 필요</span>}
                  </span>
                </button>
              </li>
            ))
          ) : (
            <li className="nodata">
              {all.length
                ? '찾는 시나리오가 없습니다.'
                : '등록된 시나리오가 없습니다. 시나리오 등록에서 승인하고 등록하면 여기에 나타납니다.'}
            </li>
          )}
        </ul>
      )}
      <p className="note">
        <b>재승인 필요</b> 시나리오는 등록 메뉴에서 다시 확인해야 담을 수 있습니다.
      </p>
    </Card>
  );
}
