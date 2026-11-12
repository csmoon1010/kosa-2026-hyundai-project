import { useStore } from '../../../lib/store';
import { parameterRows, taskLabel, type StepEntry } from './irLog';
import styles from './ir.module.css';
import { irStore, selectStep, setXmlView } from './irStore';
import { Tabs } from './Tabs';

/** 시나리오 STEP — 왼쪽 STEP 목록, 오른쪽 고른 STEP 상세 (업무 조건 · API · 대체 파라미터 · Baseline XML) */
export function StepSection() {
  const { log } = useStore(irStore);
  const entry = log.selectedStep ? log.entries[log.selectedStep] : undefined;
  return (
    <section className={styles.stepSection} aria-label="시나리오 STEP">
      <h3>시나리오 STEP</h3>
      {log.steps.length === 0 && <p className="note">승인본으로 생성하면 STEP을 표시합니다.</p>}
      <div className={styles.stepLayout}>
        <nav className={styles.stepList} aria-label="시나리오 단계 선택">
          {log.steps.map((id) => {
            const e = log.entries[id]!;
            return (
              <button
                key={id}
                type="button"
                className={styles.stepNode}
                aria-pressed={log.selectedStep === id}
                onClick={() => selectStep(id)}
              >
                <span className={styles.kicker}>{taskLabel(e)}</span>
                <strong>{e.s.edge || '단계 준비'}</strong>
                <span className={styles.state}>{e.status}</span>
              </button>
            );
          })}
        </nav>
        {entry && <StepDetail entry={entry} />}
      </div>
    </section>
  );
}

const show = (v: unknown) => (typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? '—'));

function StepDetail({ entry }: { entry: StepEntry }) {
  const { xmlView } = useStore(irStore);
  const api = entry.s.api;
  const rows = parameterRows(entry.s);
  return (
    <section className={styles.stepDetail} aria-live="polite">
      <div className={styles.heading}>
        <h3>
          STEP {entry.id} · {entry.s.edge || '단계 준비'}
        </h3>
        <span className={styles.state}>{entry.status}</span>
      </div>
      <div className={styles.context}>
        <div className={`${styles.kicker} ${styles.task}`}>
          업무 {String(entry.task_sequence ?? '—')} · {entry.task_action || ''}
        </div>
        <span className={styles.kicker}>업무 조건</span>
        <p>
          {typeof entry.conditions === 'object' && entry.conditions !== null
            ? JSON.stringify(entry.conditions, null, 2)
            : String(entry.conditions || '업무 조건이 없습니다.')}
        </p>
      </div>
      <div className={styles.api}>
        {(
          [
            ['API ID', api.api_id],
            ['Method', api.method],
            ['처리 구분값', api.selector],
            ['Endpoint', api.endpoint],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <span className={styles.kicker}>{label}</span>
            <code>{show(value)}</code>
          </div>
        ))}
      </div>
      <div>
        <h3>대체 파라미터</h3>
        <div style={{ overflowX: 'auto' }}>
          <table>
            <tbody>
              <tr>
                <th>파라미터</th>
                <th>Baseline 값</th>
                <th>적용 값 / 참조</th>
                <th>처리</th>
              </tr>
              {rows.map((r, i) => (
                <tr key={i}>
                  {r.map((c, j) => (
                    <td key={j}>{c}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className={styles.heading}>
        <h3>Baseline XML</h3>
        <span className="note">{entry.s.baseline?.validation_status || ''}</span>
      </div>
      <Tabs
        label="Baseline XML 보기"
        idPrefix="irDraftXML"
        tabs={[
          ['after', '적용 후 미리보기'],
          ['before', '원본 Baseline'],
        ]}
        value={xmlView}
        onChange={setXmlView}
      />
      <div id="irDraftXML-panel" role="tabpanel" aria-labelledby={`irDraftXML-${xmlView}`}>
        <pre className={styles.code}>
          <code>
            <Xml entry={entry} view={xmlView} />
          </code>
        </pre>
      </div>
      <p className="note">
        {'{{…}}는 실행 시 결정될 응답 참조 또는 필요한 입력입니다.'}
        {entry.preview?.available && entry.preview.warnings?.length
          ? ' ' + entry.preview.warnings.join(' ')
          : ''}
      </p>
    </section>
  );
}

const WAITING = ['대기', '분석 중', '초안 작성 · 비교 중'];

function Xml({ entry, view }: { entry: StepEntry; view: 'after' | 'before' }) {
  const preview = entry.preview;
  if (!preview?.available)
    return (
      <>
        {preview?.warnings?.join('\n') ||
          (WAITING.includes(entry.status)
            ? 'STEP 생성 후 XML 미리보기를 표시합니다.'
            : '이 결과에는 Baseline XML 미리보기 정보가 없습니다. 다시 생성해 확인하세요.')}
      </>
    );
  const lines =
    view === 'after'
      ? (preview.applied_lines ?? [])
      : (preview.original_xml ?? '').split('\n').map((text) => ({ text, changed: false }));
  return (
    <>
      {lines.map((line, i) => (
        <span key={i}>
          <span className={line.changed ? styles.xmlChange : undefined}>
            {line.text.split(/(<[^>]+>)/).map((part, j) =>
              part.startsWith('<') && part.endsWith('>') ? (
                <span key={j} className={styles.xmlTag}>
                  {part}
                </span>
              ) : (
                part
              ),
            )}
          </span>
          {'\n'}
        </span>
      ))}
    </>
  );
}
