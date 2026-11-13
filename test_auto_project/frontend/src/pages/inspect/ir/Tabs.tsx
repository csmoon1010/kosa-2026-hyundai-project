import { useRef, type KeyboardEvent } from 'react';

import styles from './ir.module.css';

/** 두 칸 탭 — 화살표 · Home · End 로 옮긴다 (예전 화면과 같다) */
export function Tabs<K extends string>({
  label,
  tabs,
  value,
  onChange,
  idPrefix,
}: {
  label: string;
  tabs: [K, string][];
  value: K;
  onChange: (key: K) => void;
  idPrefix: string;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const onKey = (event: KeyboardEvent, key: K) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const i = tabs.findIndex(([k]) => k === key);
    const next =
      event.key === 'Home'
        ? tabs[0]![0]
        : event.key === 'End'
          ? tabs[tabs.length - 1]![0]
          : tabs[(i + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]![0];
    onChange(next);
    refs.current[next]?.focus();
  };
  return (
    <div className={styles.tabs} role="tablist" aria-label={label}>
      {tabs.map(([key, text]) => (
        <button
          key={key}
          ref={(el) => {
            refs.current[key] = el;
          }}
          type="button"
          role="tab"
          id={`${idPrefix}-${key}`}
          aria-controls={`${idPrefix}-panel`}
          aria-selected={value === key}
          onClick={() => onChange(key)}
          onKeyDown={(e) => onKey(e, key)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}
