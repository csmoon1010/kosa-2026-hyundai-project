import { useEffect, useRef } from 'react';

import { Card } from '../../components/Card';
import { PageActions } from '../../components/PageActions';
import { domName } from '../../lib/format';
import { useStore } from '../../lib/store';
import { analyze, inspect, isError, newScenario } from './inspectState';
import styles from './inspect.module.css';

/** 왼쪽 — 이름 · 자연어 요청 · 도메인 · 분석 · 중지조건 · 재시도. 머리에 '＋ 새 시나리오 등록' */
export function InputCard() {
  const s = useStore(inspect);
  const utteranceRef = useRef<HTMLTextAreaElement>(null);
  const focusAfterNew = useRef(false);
  const domains =
    s.analysis && !isError(s.analysis)
      ? [...new Set(s.analysis.tasks.tasks.map((t) => domName(t.domain)))]
      : [];

  useEffect(() => {
    if (focusAfterNew.current) {
      focusAfterNew.current = false;
      utteranceRef.current?.focus();
    }
  });

  function run() {
    if (s.busy) return;
    if (!s.utterance.trim()) {
      inspect.set({ message: '자연어 요청을 입력하세요.' });
      return;
    }
    void analyze();
  }

  return (
    <>
      <PageActions>
        <button
          className="btn btn-primary"
          type="button"
          onClick={() => {
            focusAfterNew.current = true;
            newScenario();
          }}
        >
          ＋ 새 시나리오 등록
        </button>
      </PageActions>
      <Card title={s.name.trim() || '새 시나리오 — 3단계 분석'}>
        <div className="field">
          <label className="lb" htmlFor="scName">
            시나리오 이름
          </label>
          <input
            type="text"
            id="scName"
            placeholder="예) 결제완료 · 미출고 주문"
            value={s.name}
            onChange={(e) => inspect.set({ name: e.target.value })}
          />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label className="lb" htmlFor="scUtt">
            자연어 요청
          </label>
          <textarea
            id="scUtt"
            ref={utteranceRef}
            className={styles.utterance}
            spellCheck={false}
            placeholder="예) 결제는 완료됐지만 출고는 안 된 주문 2건 만들어줘"
            value={s.utterance}
            onChange={(e) => inspect.set({ utterance: e.target.value })}
          />
        </div>
        {domains.length > 0 && (
          <div className="field" style={{ margin: '10px 0 0' }}>
            <span className="lb">도메인</span>
            <div>
              {domains.map((d) => (
                <span key={d} className="tag">
                  {d}
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="btn-row">
          <button className={`btn btn-primary ${styles.wide}`} type="button" disabled={s.busy} onClick={run}>
            분석 (의도 → 경로 → API)
          </button>
          <label className={`note ${styles.stop}`}>
            <input
              type="checkbox"
              checked={s.stopRetry}
              onChange={(e) => inspect.set({ stopRetry: e.target.checked })}
            />{' '}
            중지조건 · 재시도 (①②③ · IR 생성)
          </label>
        </div>
        <p className="toast" role="status" hidden={!s.message}>
          {s.message}
        </p>
      </Card>
    </>
  );
}
