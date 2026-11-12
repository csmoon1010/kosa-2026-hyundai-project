import type { ReactNode } from 'react';

import styles from './JsonCode.module.css';

/** 값을 JSON 2칸 들여쓰기로 — 키 · 문자열 · true/false/null 에 색 (지금 화면의 beautify). 문자열로 온 JSON 은 풀어서 */
export function JsonCode({ value }: { value: unknown }) {
  let shown = value;
  if (typeof value === 'string') {
    try {
      shown = JSON.parse(value);
    } catch {
      // JSON 이 아니면 문자열 그대로
    }
  }
  const text = JSON.stringify(shown, null, 2) ?? String(shown);
  const out: ReactNode[] = [];
  const pattern = /"(?:\\.|[^"\\])*"(?=\s*:)|"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b/g;
  let end = 0;
  for (const match of text.matchAll(pattern)) {
    out.push(text.slice(end, match.index));
    const isKey =
      match[0][0] === '"' &&
      text
        .slice(match.index + match[0].length)
        .trimStart()
        .startsWith(':');
    const cls = match[0][0] === '"' ? (isKey ? styles.key : styles.string) : styles.literal;
    out.push(
      <span key={match.index} className={cls}>
        {match[0]}
      </span>,
    );
    end = match.index + match[0].length;
  }
  out.push(text.slice(end));
  return <code>{out}</code>;
}
