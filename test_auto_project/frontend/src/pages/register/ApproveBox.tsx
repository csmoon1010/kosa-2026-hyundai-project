import { useRef } from 'react';

import { useRefreshScenarios } from '../../api/queries';
import { useStored } from '../../lib/storage';
import { useStore } from '../../lib/store';
import { flow, register, setChecked } from './flow';
import type { ConfirmItem, View } from './model';
import sc from '../../components/scenario.module.css';
import styles from './register.module.css';

/** 확인할 것 체크 · 승인자 · 승인하고 등록. 등록 기록이면 체크한 것과 승인 정보만 */
export function ApproveBox({ v, confirm }: { v: View; confirm: ConfirmItem[] }) {
  const s = useStore(flow);
  const [approver, setApprover] = useStored('tdg.approver');
  const approverRef = useRef<HTMLInputElement>(null);
  const refresh = useRefreshScenarios();
  const rec = v.saved;

  const isChecked = (key: string) =>
    rec ? (rec.approval.steps ?? []).includes(key) : Boolean(s.checked[key]);
  const confirmBox = confirm.length > 0 && (
    <>
      <h3>
        확인할 것 <span className="cnt">{confirm.length}</span>
      </h3>
      <ul className={sc.checks}>
        {confirm.map((c) => (
          <li key={c.key}>
            <label>
              <input
                type="checkbox"
                checked={isChecked(c.key)}
                disabled={Boolean(rec)}
                onChange={(e) => setChecked(c.key, e.target.checked)}
              />{' '}
              <b>{c.label}</b> {c.head} — API 가 맞는지 확인했어요
            </label>
            {c.why.length > 0 && <span className={sc.why}>{c.why.join(' · ')}</span>}
          </li>
        ))}
      </ul>
    </>
  );

  if (rec)
    return (
      <div className={sc.approve}>
        {confirmBox}
        <p className={sc.done}>
          ✓ 등록됨 — 승인 {rec.approval.approver} · {rec.registered_at}
        </p>
      </div>
    );
  if (s.registered)
    return (
      <div className={sc.approve}>
        {confirmBox}
        <p className={sc.done}>✓ 등록했어요 — {s.registered.name}</p>
      </div>
    );

  const r2 = v.result.gate.steps.some((x) => x.tier === 'R2');
  const allChecked = confirm.every((c) => s.checked[c.key]);
  const ready = Boolean(s.ir) && !s.busy && allChecked;
  const why = !s.ir
    ? s.irError
      ? '시나리오를 만든 뒤 등록할 수 있어요.'
      : '시나리오를 만드는 중이에요.'
    : !allChecked
      ? '확인할 것을 모두 체크하면 등록할 수 있어요.'
      : '';

  async function onRegister() {
    const name = flow.get().name.trim();
    const who = approver.trim();
    if (!name) {
      flow.set({ regError: '시나리오 이름을 적으세요.' });
      document.getElementById('finName')?.focus();
      return;
    }
    if (!who) {
      flow.set({ regError: '승인자를 적으세요.' });
      approverRef.current?.focus();
      return;
    }
    if (await register(name, who)) {
      setApprover(who);
      await refresh();
    }
  }

  return (
    <div className={sc.approve}>
      {confirmBox}
      <div className={styles.approver}>
        <label htmlFor="finWho">승인자</label>
        <input
          type="text"
          id="finWho"
          ref={approverRef}
          placeholder="이름"
          value={approver}
          onChange={(e) => setApprover(e.target.value)}
        />
      </div>
      {r2 && <p className={sc.why}>되돌릴 수 없는 단계는 실행할 때마다 다시 확인해요.</p>}
      <div className="btn-row">
        <button
          className="btn btn-primary"
          type="button"
          disabled={!ready || s.regBusy}
          onClick={() => void onRegister()}
        >
          {s.regBusy ? '등록 중…' : '승인하고 등록'}
        </button>
      </div>
      <p className={sc.why}>{why}</p>
      {s.regError && <p className={sc.err}>{s.regError}</p>}
    </div>
  );
}
