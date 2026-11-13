import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import styles from './Modal.module.css';

/** 팝업 — 열면 닫기 버튼에 포커스, Esc · 바깥을 누르면 닫고, 닫으면 연 자리로 포커스를 돌려준다 */
export function Modal({
  eyebrow,
  title,
  wide = false,
  onClose,
  children,
}: {
  eyebrow?: string;
  title: string;
  wide?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const id = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });
  useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      back?.focus?.();
    };
  }, []);
  return createPortal(
    <div className={styles.modal}>
      <div className={styles.bg} onClick={onClose} />
      <div
        className={`${styles.box} ${wide ? styles.wide : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
      >
        <div className={styles.head}>
          <div>
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            <h2 id={id}>{title}</h2>
          </div>
          <button ref={closeRef} type="button" className={styles.close} onClick={onClose}>
            닫기
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
