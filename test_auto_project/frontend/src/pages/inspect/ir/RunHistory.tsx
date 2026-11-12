import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { get, type Schemas } from '../../../api/client';
import { OPTION_KEYS, OPTION_LABELS, emptyOptions, type GenerationOptions } from './irLog';
import styles from './ir.module.css';
import { RUN_HEADINGS, irRunsKey, runCells } from './runs';

interface Filter {
  from: string;
  to: string;
  only: boolean;
  options: GenerationOptions;
}
const noFilter = (): Filter => ({ from: '', to: '', only: false, options: emptyOptions() });

/** 누적 IR 실행 기록 — 날짜 · 생성 옵션 조합으로 거르기, JSONL 내려받기 */
export function RunHistory() {
  const runs = useQuery({
    queryKey: irRunsKey,
    queryFn: ({ signal }) => get<Schemas['IrRunList']>('/api/inspect/ir/logs', signal),
    select: (d) => d.runs,
    refetchOnMount: 'always', // 다른 메뉴에 있는 동안 생성이 끝났을 수 있다
  });
  const [f, setF] = useState<Filter>(noFilter);
  const all = runs.data ?? [];
  const shown = all.filter((run) => {
    const date = typeof run.started_at === 'string' ? run.started_at.slice(0, 10) : '';
    if (f.from && (!date || date < f.from)) return false;
    if (f.to && (!date || date > f.to)) return false;
    if (f.only && (!run.options || OPTION_KEYS.some((k) => Boolean(run.options![k]) !== f.options[k])))
      return false;
    return true;
  });
  const status = runs.isPending
    ? '저장된 JSONL 실행 로그를 불러오는 중입니다.'
    : runs.isError
      ? '저장된 IR 로그 요약을 불러오지 못했습니다.'
      : shown.length
        ? `JSONL 로그 ${shown.length} / ${all.length}개 · 최신 실행부터 표시`
        : all.length
          ? `필터 조건에 맞는 실행 로그가 없습니다. (0 / ${all.length})`
          : '저장된 실행 로그가 없습니다.';

  return (
    <section className={styles.history} aria-label="누적 IR 실행 로그">
      <h3>누적 IR 실행 기록</h3>
      <div className={styles.filters} aria-label="실행 기록 필터">
        <label>
          시작일 <input type="date" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} />
        </label>
        <label>
          종료일 <input type="date" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} />
        </label>
        <fieldset className={styles.optionFilters}>
          <legend>생성 옵션</legend>
          <label>
            <input
              type="checkbox"
              checked={f.only}
              onChange={(e) => setF({ ...f, only: e.target.checked })}
            />{' '}
            선택한 조합만 표시
          </label>
          <div>
            {OPTION_KEYS.map((k) => (
              <label key={k}>
                <input
                  type="checkbox"
                  checked={f.options[k]}
                  onChange={(e) => setF({ ...f, options: { ...f.options, [k]: e.target.checked } })}
                />{' '}
                {OPTION_LABELS[k]}
              </label>
            ))}
          </div>
        </fieldset>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setF(noFilter())}>
          필터 초기화
        </button>
      </div>
      <p className="note">{status}</p>
      {shown.length > 0 && (
        <div className={styles.logWrap}>
          <table className={`${styles.logTable} ${styles.runTable}`}>
            <thead>
              <tr>
                {RUN_HEADINGS.map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((run, i) => (
                <tr key={run.run_id ?? i}>
                  {runCells(run).map((c, j) => (
                    <td key={j}>{c}</td>
                  ))}
                  <td>
                    {typeof run.filename === 'string' && /^IRRUN-[A-Za-z0-9-]+\.jsonl$/.test(run.filename) ? (
                      <a
                        href={'/api/inspect/ir/logs/' + encodeURIComponent(run.filename)}
                        download={run.filename}
                      >
                        JSONL
                      </a>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
