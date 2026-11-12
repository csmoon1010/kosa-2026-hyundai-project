import type { ReactNode } from 'react';

import styles from './Pill.module.css';

/** 상태 알약 — good(선택 · 통과) · signal(가선택 · 확인) · danger(차단 · 되돌릴 수 없음) · accent · muted (지금 .st-ok · .st-rb …) */
export type Tone = 'good' | 'signal' | 'danger' | 'accent' | 'muted';

export function Pill({
  tone = 'muted',
  children,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`${styles.pill} ${styles[tone]}`} title={title}>
      {children}
    </span>
  );
}
