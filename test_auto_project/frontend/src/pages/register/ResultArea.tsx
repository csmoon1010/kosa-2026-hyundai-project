import { useEffect, useRef } from 'react';

import { useRegisteredRecord } from '../../api/queries';
import { Card } from '../../components/Card';
import { Spinner } from '../../components/Spinner';
import { Stepper } from '../../components/Stepper';
import { clean } from '../../lib/format';
import { useStore } from '../../lib/store';
import { analyze, closeSaved, flow } from './flow';
import { STAGES, viewFromRecord, type View } from './model';
import { useGenerationOptions } from './options';
import { Preview } from './Preview';
import styles from './register.module.css';

/** 오른쪽 — 진행 4단계 + 결과(미리보기 · 멈춤). 등록 기록을 열었으면 그 기록 */
export function ResultArea() {
  const s = useStore(flow);
  const saved = useRegisteredRecord(s.viewingId);
  const out = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!saved.isError) return;
    flow.set({ message: '불러오지 못했어요: ' + saved.error.message });
    closeSaved();
  }, [saved.isError, saved.error]);

  useEffect(() => {
    if (saved.data) out.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }, [saved.data]);

  const viewing = Boolean(s.viewingId);
  const showProgress = !viewing && (s.busy || Boolean(s.result) || Boolean(s.analysisError));
  const irCount =
    s.stages.ir === 'now' && s.irTotal ? `${Object.keys(s.irSteps).length}/${s.irTotal}` : undefined;

  return (
    <>
      {showProgress && (
        <Card>
          <Stepper
            steps={STAGES.map(([key, label]) => ({
              key,
              label,
              state: s.stages[key] ?? 'wait',
              count: key === 'ir' ? irCount : undefined,
            }))}
          />
        </Card>
      )}
      <div ref={out} aria-live="polite" aria-busy={s.busy || undefined}>
        {viewing ? (
          saved.data ? (
            <Preview v={viewFromRecord(saved.data)} />
          ) : (
            saved.isPending && <Spinner block label="등록 기록 불러오는 중" />
          )
        ) : (
          <Current />
        )}
      </div>
    </>
  );
}

/** 지금 분석한 것 */
function Current() {
  const s = useStore(flow);
  const [options] = useGenerationOptions();
  if (s.analysisError)
    return (
      <Stopped title="분석하지 못했어요" items={[s.analysisError]} onRetry={() => void analyze(options)} />
    );
  if (!s.result) return null;
  const { gate, tasks } = s.result;
  if (gate.status === '차단') return <Stopped title="이 요청은 등록할 수 없어요" items={gate.blocked} />;
  if (gate.status === '실행할 것 없음')
    return <Stopped title="실행할 단계가 없어요" items={tasks.unresolved} />;
  const v: View = {
    result: s.result,
    stepMap: s.stepMap,
    irSteps: s.irSteps,
    ir: s.ir,
    irError: s.irError,
    irRunning: s.stages.ir === 'now',
    saved: null,
  };
  return <Preview v={v} />;
}

function Stopped({ title, items, onRetry }: { title: string; items: string[]; onRetry?: () => void }) {
  return (
    <Card className={`fade ${styles.stop}`} title={title}>
      {items.length > 0 && (
        <ul>
          {items.map((x, i) => (
            <li key={i}>{clean(x)}</li>
          ))}
        </ul>
      )}
      {onRetry && (
        <div className="btn-row">
          <button className="btn btn-ghost btn-sm" type="button" onClick={onRetry}>
            다시 분석
          </button>
        </div>
      )}
    </Card>
  );
}
