import { useState } from 'react';

import { JsonCode } from '../../components/JsonCode';
import styles from './inspect.module.css';

/** 단계 출력 JSON 전체 — 서버가 돌려준 그대로, 복사 버튼 */
export function JsonDetails({ label, value }: { label: string; value: unknown }) {
  const [copied, setCopied] = useState<'' | '복사됨' | '복사 실패'>('');
  const copy = () => {
    try {
      navigator.clipboard.writeText(JSON.stringify(value, null, 2)).then(
        () => {
          setCopied('복사됨');
          window.setTimeout(() => setCopied(''), 1500);
        },
        () => setCopied('복사 실패'),
      );
    } catch {
      setCopied('복사 실패');
    }
  };
  return (
    <details className={styles.json}>
      <summary className="btn btn-ghost btn-sm">{label} 출력 JSON 전체 보기</summary>
      <div style={{ marginTop: 8 }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={copy}>
          {copied || '복사'}
        </button>
        <pre>
          <JsonCode value={value} />
        </pre>
      </div>
    </details>
  );
}
