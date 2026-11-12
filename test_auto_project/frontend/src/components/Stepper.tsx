import { Spinner } from './Spinner';
import styles from './Stepper.module.css';

/** wait 대기 · now 진행 중 · done 완료 · fail 멈춤 · off 쓰지 않음 (지금 .fin-steps) */
export type StepState = 'wait' | 'now' | 'done' | 'fail' | 'off';

export interface StepItem {
  key: string;
  label: string;
  state: StepState;
  /** 진행 중 숫자 (예: '3/5') */
  count?: string;
}

const SAY: Record<StepState, string> = { now: '진행 중', done: '완료', fail: '멈춤', wait: '대기', off: '' };

export function Stepper({ steps, label = '진행 단계' }: { steps: StepItem[]; label?: string }) {
  return (
    <ol className={styles.steps} aria-label={label} aria-live="polite">
      {steps.map((step, i) => (
        <li key={step.key} data-s={step.state}>
          <span className={styles.dot} aria-hidden="true">
            {step.state === 'now' ? (
              <Spinner size="small" label="" />
            ) : step.state === 'done' ? (
              '✓'
            ) : step.state === 'fail' ? (
              '!'
            ) : (
              i + 1
            )}
          </span>
          <span>
            {step.label}
            {step.state === 'now' && step.count && <span className={styles.count}>{step.count}</span>}
          </span>
          {SAY[step.state] && <span className="sr-only"> — {SAY[step.state]}</span>}
        </li>
      ))}
    </ol>
  );
}
