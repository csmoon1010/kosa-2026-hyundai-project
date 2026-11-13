import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { Card } from '../../../components/Card';
import { JsonCode } from '../../../components/JsonCode';
import { useStore } from '../../../lib/store';
import { useNow } from '../../../lib/useNow';
import { OPTION_KEYS, OPTION_LABELS, progressText } from './irLog';
import styles from './ir.module.css';
import { choose, generate, irStore, refresh, resetOptions, setOption } from './irStore';
import { LogPanel } from './LogPanel';
import { RunHistory } from './RunHistory';
import { irRunsKey } from './runs';
import { StepSection } from './StepSection';

/** 혜정 IR 영역 — 저장된 승인본으로 IR 초안 생성 · 진행 로그 · STEP 상세 · 누적 실행 기록 (예전 web/scenario-ir-draft.js) */
export function IrArea() {
  const s = useStore(irStore);
  const now = useNow(s.busy);
  const client = useQueryClient();
  const wasBusy = useRef(s.busy);

  useEffect(() => {
    if (!irStore.get().loaded) refresh().catch((e: Error) => irStore.set({ status: e.message }));
  }, []);

  useEffect(() => {
    if (wasBusy.current && !s.busy) void client.invalidateQueries({ queryKey: irRunsKey });
    wasBusy.current = s.busy;
  }, [s.busy, client]);

  const logUrl = s.log.logFile?.log_url;
  const ir = s.result?.ir;

  return (
    <Card className={styles.area} title="IR 초안 생성 · 결과">
      <section id="scenarioIRDraft" aria-label="IR 초안 생성 및 결과">
        <div>{s.settings}</div>
        <fieldset className={styles.options}>
          <legend>생성 옵션 · 함께 선택 가능</legend>
          {OPTION_KEYS.map((key) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={s.options[key]}
                disabled={s.busy}
                onChange={(e) => setOption(key, e.target.checked)}
              />{' '}
              {OPTION_LABELS[key]}
            </label>
          ))}
        </fieldset>
        <p className={`note ${styles.modeStatus}`}>{s.log.modeStatus}</p>
        <button type="button" className="btn btn-ghost" disabled={s.busy} onClick={resetOptions}>
          옵션 기본값 복원
        </button>
        <p className={styles.files}>
          <label>
            저장된 승인본
            <select value={s.selected} disabled={s.busy} onChange={(e) => choose(e.target.value)}>
              {!s.files.some((f) => f.filename === s.selected) && <option value="" />}
              {s.files.map((f) => (
                <option key={f.filename} value={f.filename}>
                  {f.filename} · {f.original_question}
                </option>
              ))}
            </select>
          </label>
        </p>
        <button
          type="button"
          className="btn btn-primary"
          disabled={s.busy || !s.budget}
          onClick={() => void generate()}
        >
          IR 다시 생성
        </button>
        <p role="status">{s.status}</p>
        {s.log.logFile && (
          <p>
            <span>전체 로그: {s.log.logFile.log_file} </span>
            {logUrl?.startsWith('/api/inspect/ir/logs/') && (
              <a href={logUrl} download="">
                JSONL 다운로드
              </a>
            )}
          </p>
        )}
        <StepSection />
        <div aria-live="polite">
          {s.started ? progressText(s.log, s.started, s.busy ? now : s.ended || now) : ''}
        </div>
        <LogPanel now={s.busy ? now : s.ended || now} />
        {ir && (
          <div>
            <p>
              {ir.scenario_id} v{String(ir.version)} · {ir.status} · 저장: {s.result?.file}
            </p>
            <details className={styles.jsonView}>
              <summary>IR JSON · Beautify</summary>
              <pre className={styles.code}>
                <JsonCode value={ir} />
              </pre>
            </details>
          </div>
        )}
        <RunHistory />
      </section>
    </Card>
  );
}
