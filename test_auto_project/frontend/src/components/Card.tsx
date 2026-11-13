import type { ReactNode } from 'react';

import styles from './Card.module.css';

interface Props {
  title?: ReactNode;
  /** 제목 위 작은 글씨 (예전 화면의 .eyebrow) */
  eyebrow?: ReactNode;
  /** 제목 줄 오른쪽 (버튼 등) */
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
}

export function Card({ title, eyebrow, actions, children, className }: Props) {
  const hasHead = title !== undefined || eyebrow !== undefined || actions !== undefined;
  return (
    <section className={[styles.card, className].filter(Boolean).join(' ')}>
      {hasHead && (
        <div className={styles.head}>
          <div>
            {eyebrow !== undefined && <p className="eyebrow">{eyebrow}</p>}
            {title !== undefined && <h2 className={styles.title}>{title}</h2>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
