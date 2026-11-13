import { useState } from 'react';

import { Modal } from '../../../components/Modal';
import { useStore } from '../../../lib/store';
import {
  issues,
  search,
  stateFieldOptions,
  toYaml,
  type Data,
  type GraphEntry,
  type GState,
  type View,
} from './editorModel';
import { editor } from './editorStore';
import styles from './graph.module.css';

const close = () => editor.set({ modal: null });

/** 시험해 보기 — 화살표만으로 출발 → 목표 경로 (이름 없는 화살표는 빼고) */
export function TestDialog({ g, v }: { g: GraphEntry; v: View }) {
  const e = useStore(editor);
  const placed = v.placed();
  const T = e.test[g.id] ?? { from: '', target: '', must: '' };
  const target = T.target && placed.includes(T.target) ? T.target : (placed[placed.length - 1] ?? '');
  const from = T.from && placed.includes(T.from) ? T.from : (placed[0] ?? '');
  const must = T.must;
  const set = (patch: Partial<typeof T>) =>
    editor.set((st) => ({ test: { ...st.test, [g.id]: { from, target, must, ...patch } } }));
  const p = target && from ? search(v, from, target, must || null) : null;
  const opts = (none: boolean) => (
    <>
      {none && <option value="">(없음)</option>}
      {placed.map((c) => (
        <option key={c} value={c}>
          {v.sn(c)}
        </option>
      ))}
    </>
  );
  return (
    <Modal title="시험해 보기" onClose={close}>
      <div className={styles.form}>
        <div className={styles.two}>
          <div className={styles.fld}>
            <label htmlFor="ge-tf">출발 상태</label>
            <select id="ge-tf" value={from} onChange={(ev) => set({ from: ev.target.value })}>
              {opts(false)}
            </select>
          </div>
          <div className={styles.fld}>
            <label htmlFor="ge-tt">목표 상태</label>
            <select id="ge-tt" value={target} onChange={(ev) => set({ target: ev.target.value })}>
              {opts(false)}
            </select>
          </div>
        </div>
        <div className={styles.fld}>
          <label htmlFor="ge-tm">그 전에 거쳐야 할 상태</label>
          <select id="ge-tm" value={must} onChange={(ev) => set({ must: ev.target.value })}>
            {opts(true)}
          </select>
        </div>
        <div className={`${styles.box} ${styles.path}`} role="status">
          {!target ? (
            <span className={styles.note}>상태를 먼저 캔버스에 놓으세요.</span>
          ) : p ? (
            <div>
              <span className={`${styles.st} ${styles.stOk}`}>경로</span>
              <br />
              {v.sn(from)}
              {p.map((x) => ` → ${x.name} → ${v.sn(x.to)}`).join('')}{' '}
              <span className={styles.note}>· 화살표 {p.length}개</span>
            </div>
          ) : (
            <div>
              <span className={`${styles.st} ${styles.stErr}`}>경로 없음</span>
              <br />
              <span style={{ fontFamily: 'var(--sans)' }}>
                {v.sn(from)} 에서 {v.sn(target)}(으)로 가는 화살표 길이 없습니다 (이름 없는 화살표는 빼고
                계산).
              </span>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

/** 저장 — 저장되는 것 · 먼저 끝낼 것 · 저장될 YAML 보기 → 확인 후 저장 */
export function SaveDialog({
  g,
  s,
  v,
  onSave,
}: {
  g: GraphEntry;
  s: GState;
  v: View;
  onSave: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const err = issues(s, v).filter((x) => x.lv === 'err');
  const w = v.workEdges();
  const conf = w.filter((e) => e.name).length;
  return (
    <Modal title="저장" onClose={close}>
      <div className={styles.form}>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.8 }}>
          <li>
            저장되는 화살표 <b>{conf}</b>개 (이름을 적은 것)
          </li>
          {w.length - conf > 0 && <li>저장 안 되는 화살표 {w.length - conf}개 (이름 없음)</li>}
          <li>
            상태 필드{' '}
            {s.stateField.st === '확정' ? (
              <span className={styles.mono}>{s.stateField.v}</span>
            ) : (
              '확정 전 — 빠짐'
            )}
          </li>
        </ul>
        {err.length > 0 && (
          <div className={`${styles.box} ${styles.warn}`}>
            <b>먼저 끝내야 할 것 {err.length}개</b>
            {err.map((x, i) => (
              <p key={i} className={styles.ev}>
                {x.msg}
              </p>
            ))}
          </div>
        )}
        <details>
          <summary style={{ fontSize: 12.5, fontWeight: 500, cursor: 'pointer' }}>저장될 내용 보기</summary>
          <pre className={styles.yaml}>{toYaml(g, s, v)}</pre>
        </details>
        <div className={styles.row}>
          <button
            type="button"
            className={`${styles.gbtn} ${styles.pri}`}
            disabled={err.length > 0 || busy}
            onClick={() => {
              setBusy(true);
              void onSave().finally(() => setBusy(false));
            }}
          >
            확인 후 저장
          </button>
          <button type="button" className={`${styles.gbtn} ${styles.ghost}`} onClick={close}>
            취소
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** 그래프 설정 — 조회 결과에서 현재 상태를 읽는 필드 (자동 추정 → 확정) */
export function SettingsDialog({
  s,
  D,
  onField,
  onConfirm,
}: {
  s: GState;
  D: Data;
  onField: (f: string) => void;
  onConfirm: () => void;
}) {
  const options = stateFieldOptions(s, D.ops);
  return (
    <Modal title="그래프 설정" onClose={close}>
      <div className={styles.form}>
        <div className={styles.fld}>
          <label htmlFor="ge-sf">조회 결과에서 현재 상태를 읽는 필드</label>
          <select id="ge-sf" value={s.stateField.v ?? ''} onChange={(e) => onField(e.target.value)}>
            {options.map(([f, l]) => (
              <option key={f} value={f}>
                {f} · {l.slice(0, 2).join(', ')}
              </option>
            ))}
          </select>
          <span className={styles.hint}>자동으로 추정한 값입니다.</span>
        </div>
        <div className={styles.row}>
          {s.stateField.st === '확정' ? (
            <span className={`${styles.st} ${styles.stOk}`}>확정</span>
          ) : (
            <button type="button" className={`${styles.gbtn} ${styles.pri}`} onClick={onConfirm}>
              확정
            </button>
          )}
          <button type="button" className={`${styles.gbtn} ${styles.ghost}`} onClick={close}>
            닫기
          </button>
        </div>
      </div>
    </Modal>
  );
}
