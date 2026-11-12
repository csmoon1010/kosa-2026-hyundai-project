import { Card } from '../../components/Card';
import { ParamTable } from '../../components/ParamTable';
import { apiCode, clean, domName } from '../../lib/format';
import { ApproveBox } from './ApproveBox';
import { closeSaved, rebuild } from './flow';
import { apiLabel, apiName, irStepOf, keyOf, memos, toConfirm, type Row, type View } from './model';
import { useGenerationOptions } from './options';
import sc from '../../components/scenario.module.css';
import styles from './register.module.css';

/** 시나리오 미리보기 — 업무마다 단계 카드 · 입력값 표, 메모, 승인 · 등록. 등록 기록을 열었으면 읽기 전용 */
export function Preview({ v }: { v: View }) {
  const [options] = useGenerationOptions();
  const { tasks, apis, gate } = v.result;
  const rows = apis.api_selection_results;
  const confirm = toConfirm(v.result);
  const memo = memos(v);
  const r2 = gate.steps.filter((s) => s.tier === 'R2').length;

  return (
    <Card
      className="fade"
      title={v.saved ? v.saved.name : '시나리오 미리보기'}
      actions={
        <span className={sc.sum}>
          단계 {rows.length}개{r2 ? ` · 되돌릴 수 없는 단계 ${r2}개` : ''}
          {confirm.length ? ` · 확인할 것 ${confirm.length}개` : ''}
        </span>
      }
    >
      {v.saved && <p className={styles.cond}>{v.saved.utterance}</p>}
      {v.irError && (
        <div className={styles.irFail} role="alert">
          <b>시나리오를 만들지 못했어요</b>
          <span>{clean(v.irError)}</span>
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => void rebuild(options)}>
            다시 만들기
          </button>
        </div>
      )}
      {tasks.tasks.map((t) => {
        const mine = rows.filter((r) => r.path_sequence === t.sequence).sort((a, b) => a.step - b.step);
        return (
          <section key={t.sequence} className={sc.task}>
            {/* 업무는 짧은 이름(배송완료) 대신 설명 문장으로 */}
            <div className={sc.taskHead}>
              <b>업무 {t.sequence}</b> <span className={styles.taskDesc}>{t.conditions || t.action}</span>
              <span className="tag">{domName(t.domain)}</span>
              <span className="tag">{t.origin}</span>
              {t.count ? <span className="tag">{t.count}건</span> : null}
            </div>
            {mine.length ? (
              <ol className={sc.steps}>
                {mine.map((r, i) => (
                  <StepRow key={keyOf(r)} v={v} row={r} n={i + 1} />
                ))}
              </ol>
            ) : (
              <p className="nodata">이 업무에 실행할 단계가 없어요.</p>
            )}
          </section>
        );
      })}
      {memo.length > 0 && (
        <details className={sc.memo}>
          <summary>메모 {memo.length}개</summary>
          <ul>
            {memo.map((m, i) => (
              <li key={i}>
                {m.text}
                {m.where && <span className={sc.why}>{m.where}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
      <ApproveBox v={v} confirm={confirm} />
      {v.saved && (
        <div className="btn-row">
          <button className="btn btn-ghost btn-sm" type="button" onClick={closeSaved}>
            닫기
          </button>
        </div>
      )}
    </Card>
  );
}

function StepRow({ v, row, n }: { v: View; row: Row; n: number }) {
  const g = v.result.gate.steps.find((s) => s.key === keyOf(row));
  const ir = irStepOf(v, row);
  return (
    <li className={sc.step}>
      <span className={sc.kind}>
        <b>{n}</b> {row.kind}
      </span>
      <div>
        <div className={sc.edge}>
          {row.edge}{' '}
          {row.kind === '상태변경' && row.from && row.to && (
            <span className={styles.move}>
              {row.from} → {row.to}
            </span>
          )}
        </div>
        {row.selected && (
          <span className={sc.api}>
            {apiLabel(row)}
            {apiName(row) && <span className="mono"> {apiCode(row.selected.api_id)}</span>}
          </span>
        )}
        {ir && row.selected ? (
          <ParamTable apiId={row.selected.api_id} inputs={ir.inputs} bindings={ir.bindings} />
        ) : v.irRunning ? (
          <div className={styles.wait}>입력값 만드는 중…</div>
        ) : null}
      </div>
      <div className={sc.badges}>
        {g?.tier === 'R2' && <span className={`${sc.badge} ${sc.warnB}`}>되돌릴 수 없음</span>}
        {/* 가선택 · LLM 이 고른 API */}
        {g?.requirement === '단계 승인' && <span className={`${sc.badge} ${sc.chkB}`}>확인 필요</span>}
      </div>
    </li>
  );
}
