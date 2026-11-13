import { useState } from 'react';

import { useStore } from '../../../lib/store';
import { issues, key, type EEdge, type GState, type View } from './editorModel';
import { editor } from './editorStore';
import styles from './graph.module.css';

const MARK = {
  err: <span className={`${styles.st} ${styles.stErr}`}>필수</span>,
  warn: <span className={`${styles.st} ${styles.stNone}`}>확인</span>,
  info: <span className={`${styles.st} ${styles.stExt}`}>참고</span>,
};
const ORDER = { err: 0, warn: 1, info: 2 };

interface Props {
  s: GState;
  v: View;
  onName: (k: string, name: string) => void;
  onRemoveEdge: (k: string, how: 'button' | 'silent') => void;
}

/** 오른쪽 — 화살표를 고르면 이름 적기, 아니면 다음 할 일 */
export function Inspector({ s, v, onName, onRemoveEdge }: Props) {
  const { sel } = useStore(editor);
  const edge = sel.kind === 'edge' ? v.edgeOf(sel.id) : undefined;
  return (
    <aside className={styles.insp}>
      {edge ? (
        <EdgeForm key={key(edge.from, edge.to)} e={edge} v={v} onName={onName} onRemoveEdge={onRemoveEdge} />
      ) : (
        <Todo s={s} v={v} />
      )}
    </aside>
  );
}

function Todo({ s, v }: { s: GState; v: View }) {
  const { allTodo } = useStore(editor);
  const iss = issues(s, v).sort((a, b) => ORDER[a.lv] - ORDER[b.lv]);
  const shown = allTodo ? iss : iss.slice(0, 3);
  return (
    <section className={`${styles.gcard} ${styles.form}`}>
      <div className={styles.row} style={{ justifyContent: 'space-between' }}>
        <h3>다음 할 일</h3>
        <span className={styles.note}>{iss.filter((x) => x.lv !== 'info').length}개 남음</span>
      </div>
      <div className={styles.todo}>
        {shown.length ? (
          shown.map((x, i) => (
            <button
              key={i}
              type="button"
              onClick={() =>
                x.open === 'set' ? editor.set({ modal: 'settings' }) : editor.set({ sel: x.sel })
              }
            >
              {MARK[x.lv]}
              <span>{x.msg}</span>
            </button>
          ))
        ) : (
          <p className={styles.note}>
            남은 일이 없습니다. 위의 <b>저장</b>을 누르세요.
          </p>
        )}
      </div>
      {iss.length > 3 && (
        <button
          type="button"
          className={`${styles.gbtn} ${styles.sm} ${styles.ghost}`}
          onClick={() => editor.set({ allTodo: !allTodo })}
        >
          {allTodo ? '접기' : `전체 보기 (${iss.length})`}
        </button>
      )}
      <p className={styles.note}>
        화살표를 누르면 여기서 이름을 적습니다. 상태는 끌어서 옮기고, 눌러서 나오는 × 로 뺍니다.
      </p>
    </section>
  );
}

function EdgeForm({ e, v, onName, onRemoveEdge }: { e: EEdge; v: View } & Omit<Props, 's' | 'v'>) {
  const [name, setName] = useState(e.name);
  const k = key(e.from, e.to);
  const close = () => editor.set({ sel: { kind: 'none' } });
  const title = `${v.NAME(e.from)} → ${v.NAME(e.to)}`;
  if (v.isExternal(e))
    return (
      <section className={`${styles.gcard} ${styles.form}`}>
        <div className={styles.row} style={{ justifyContent: 'space-between' }}>
          <h3>{title}</h3>
          <span className={`${styles.st} ${styles.stExt}`}>외부</span>
        </div>
        <p className={styles.note}>
          출발 상태 {v.sn(e.from)} 이(가) &apos;외부에서 생기는 상태&apos;라서 이 변화는 고객 주문 · 결제처럼
          우리 밖에서 일어납니다. API 가 필요 없습니다.
        </p>
        <div className={styles.row}>
          <button
            type="button"
            className={`${styles.gbtn} ${styles.sm} ${styles.dng}`}
            onClick={() => onRemoveEdge(k, 'silent')}
          >
            화살표 지우기
          </button>
          <button type="button" className={`${styles.gbtn} ${styles.sm} ${styles.ghost}`} onClick={close}>
            닫기
          </button>
        </div>
      </section>
    );
  const rev = v.edgeOf(key(e.to, e.from));
  return (
    <section className={`${styles.gcard} ${styles.form}`}>
      <div className={styles.row} style={{ justifyContent: 'space-between' }}>
        <h3>{title}</h3>
        {e.name ? (
          <span className={`${styles.st} ${styles.stOk}`}>확정</span>
        ) : (
          <span className={`${styles.st} ${styles.stNone}`}>이름 없음</span>
        )}
      </div>
      <div className={styles.fld}>
        <div className={styles.two}>
          <input
            type="text"
            value={name}
            placeholder="업무에서 부르는 이름 · 예: 출고완료취소"
            aria-label="업무에서 부르는 이름"
            onChange={(ev) => setName(ev.target.value)}
            onKeyDown={(ev) => {
              if (ev.key === 'Enter') {
                ev.preventDefault();
                onName(k, name);
              }
            }}
          />
          <button type="button" className={`${styles.gbtn} ${styles.pri}`} onClick={() => onName(k, name)}>
            {e.name ? '이름 바꾸기' : '확정'}
          </button>
        </div>
        <span className={styles.hint}>화면 · 업무에서 쓰는 말 그대로 적어 주세요.</span>
      </div>
      {!rev && (
        <div className={styles.box}>
          <p className={styles.ev}>
            되돌리는 화살표({v.NAME(e.to)} → {v.NAME(e.from)})가 없습니다. 실행 중 실패하면 이 단계는 되돌릴
            수 없어요. 필요하면 캔버스에서 {v.NAME(e.to)} 의 ● 을 끌어 {v.NAME(e.from)} 에 놓으세요.
          </p>
        </div>
      )}
      <div className={styles.row}>
        <button
          type="button"
          className={`${styles.gbtn} ${styles.sm} ${styles.dng}`}
          onClick={() => onRemoveEdge(k, 'button')}
        >
          화살표 지우기
        </button>
        <button type="button" className={`${styles.gbtn} ${styles.sm} ${styles.ghost}`} onClick={close}>
          닫기
        </button>
      </div>
    </section>
  );
}
