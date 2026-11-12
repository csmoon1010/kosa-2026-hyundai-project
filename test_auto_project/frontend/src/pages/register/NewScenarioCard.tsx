import { useRef } from 'react';

import { Card } from '../../components/Card';
import { useStore } from '../../lib/store';
import { analyze, flow } from './flow';
import { useGenerationOptions } from './options';
import styles from './register.module.css';

export function NewScenarioCard() {
  const { name, utterance, message, busy } = useStore(flow);
  const [options, setOption] = useGenerationOptions();
  const utteranceRef = useRef<HTMLTextAreaElement>(null);

  function run() {
    if (busy) return;
    if (!utterance.trim()) {
      flow.set({ message: '자연어 요청을 입력하세요.' });
      utteranceRef.current?.focus();
      return;
    }
    void analyze(options);
  }

  return (
    <Card title="새 시나리오">
      <div className="field">
        <label className="lb" htmlFor="finName">
          시나리오 이름
        </label>
        <input
          type="text"
          id="finName"
          placeholder="예) 배송완료 주문 취소"
          value={name}
          onChange={(e) => flow.set({ name: e.target.value })}
        />
      </div>
      <div className="field">
        <label className="lb" htmlFor="finUtt">
          자연어 요청
        </label>
        <textarea
          id="finUtt"
          ref={utteranceRef}
          className={styles.utterance}
          spellCheck={false}
          placeholder="예) 배송완료된 주문 3건을 배송완료 취소시켜줘"
          value={utterance}
          onChange={(e) => flow.set({ utterance: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run();
          }}
        />
      </div>
      <fieldset className={styles.opts}>
        <legend className="lb">시나리오 생성 옵션</legend>
        <label>
          <input
            type="checkbox"
            checked={options.kb_rag}
            onChange={(e) => setOption('kb_rag', e.target.checked)}
          />{' '}
          압축 1 · 조건별 ParameterKB 검색
        </label>
        <label>
          <input
            type="checkbox"
            checked={options.dependency_projection}
            onChange={(e) => setOption('dependency_projection', e.target.checked)}
          />{' '}
          압축 2 · 의존성 기반 STEP 문맥 선별
        </label>
      </fieldset>
      <div className="btn-row">
        <button className={`btn btn-primary ${styles.wide}`} type="button" disabled={busy} onClick={run}>
          분석
        </button>
      </div>
      <p className="toast" role="status" hidden={!message}>
        {message}
      </p>
    </Card>
  );
}
