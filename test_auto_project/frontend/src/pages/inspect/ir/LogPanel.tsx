import { JsonCode } from '../../../components/JsonCode';
import { useStore } from '../../../lib/store';
import { detailOf, rowCells } from './irLog';
import styles from './ir.module.css';
import { irStore, selectRow, setDetailTab } from './irStore';
import { Tabs } from './Tabs';

const HEADINGS = [
  '전체 턴',
  'STEP 내 턴',
  'STEP',
  '종류 / 도구',
  '상태',
  '소요시간',
  '토큰 이번 / 누적',
  'valid',
];

/** 생성 과정 · 턴 / 도구 호출 — 행을 고르면 아래에 요청 / 응답 */
export function LogPanel({ now }: { now: number }) {
  const { log, detailTab } = useStore(irStore);
  const selected = log.selectedKey ? log.rows[log.selectedKey] : undefined;
  const detail = detailOf(selected, detailTab);
  return (
    <>
      <h3>생성 과정 · 턴 / 도구 호출</h3>
      <div className={styles.logWrap}>
        <table className={styles.logTable}>
          <thead>
            <tr>
              {HEADINGS.map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {log.order.map((key) => {
              const row = log.rows[key]!;
              const cells = rowCells(row, now);
              const isSelected = log.selectedKey === key;
              return (
                <tr key={key} data-selected={isSelected} onClick={() => selectRow(key)}>
                  {cells.map((c, i) =>
                    i === 3 ? (
                      <td key={i}>
                        <button
                          type="button"
                          className={styles.select}
                          aria-pressed={isSelected}
                          aria-label={`${row.turn}턴 STEP ${row.step_id} ${row.tool || 'LLM'} 상세 보기`}
                        >
                          {c}
                        </button>
                      </td>
                    ) : (
                      <td key={i}>{c}</td>
                    ),
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <section className={styles.detail} aria-label="선택한 로그 상세">
        <h3 aria-live="polite">{detail.title}</h3>
        <Tabs
          label="요청 및 응답"
          idPrefix="irDraftDetail"
          tabs={[
            ['request', '요청 프롬프트 / 인자'],
            ['response', '응답 결과'],
          ]}
          value={detailTab}
          onChange={setDetailTab}
        />
        <div id="irDraftDetail-panel" role="tabpanel" aria-labelledby={`irDraftDetail-${detailTab}`}>
          <p className="note">{detail.meta}</p>
          <pre>
            <JsonCode value={detail.value} />
          </pre>
        </div>
      </section>
    </>
  );
}
