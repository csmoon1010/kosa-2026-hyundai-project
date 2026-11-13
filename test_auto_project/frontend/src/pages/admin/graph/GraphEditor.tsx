import { ReactFlowProvider } from '@xyflow/react';
import { useEffect, useRef, type KeyboardEvent } from 'react';

import { Spinner } from '../../../components/Spinner';
import { useToast } from '../../../lib/useToast';
import { Canvas } from './Canvas';
import { SaveDialog, SettingsDialog, TestDialog } from './Dialogs';
import { DOMS, freeGroups, guessField, nameOf, type Data, type GraphEntry } from './editorModel';
import { editor } from './editorStore';
import styles from './graph.module.css';
import { Inspector } from './Inspector';
import { Palette } from './Palette';
import { createGraph, useGraphEditor } from './useGraphEditor';

/** 상태 그래프 만들기 — 업무 담당자용 캔버스 편집기 (도메인 탭 맨 위). dom 은 실제 도메인 코드 (od · pd · ds) */
export function GraphEditor({ dom }: { dom: string }) {
  const [toast, show] = useToast(2800);
  const ed = useGraphEditor(dom, show);
  const { e } = ed;

  const toastLine = toast ? (
    <p className={styles.toast} role="status">
      {toast}
    </p>
  ) : null;

  if (!ed.ready || !ed.D) return <Spinner block label="상태 그래프 불러오는 중" />;
  const D = ed.D;
  if (e.creating)
    return (
      <div className={styles.ge}>
        <Bar mine={ed.mine} current={ed.g?.id} />
        <CreateCard D={D} dom={dom} all={ed.all} toast={show} />
        {toastLine}
      </div>
    );
  if (!ed.mine.length)
    return (
      <div className={styles.ge}>
        <div className={`${styles.gcard} ${styles.emptyst}`}>
          <span className={`${styles.st} ${styles.stExt}`}>그래프 없음</span>
          <h3>이 도메인이 주인인 상태 그래프가 없습니다</h3>
          <p className={styles.note} style={{ maxWidth: '62ch' }}>
            이 도메인이 주인인 상태 코드 그룹을 받으면 여기서 그래프를 만들 수 있습니다.
          </p>
          <button
            type="button"
            className={styles.gbtn}
            onClick={() => editor.set({ creating: true, newG: null })}
          >
            새 그래프
          </button>
        </div>
        {toastLine}
      </div>
    );
  if (!ed.g || !ed.s || !ed.v) return <Spinner block label="상태 그래프 불러오는 중" />;
  const { g, s, v } = ed;

  const onKey = (ev: KeyboardEvent) => {
    if (e.sel.kind === 'none' || e.modal || /INPUT|SELECT|TEXTAREA/.test((ev.target as HTMLElement).tagName))
      return;
    if (ev.key === 'Escape') ed.select({ kind: 'none' });
    else if (ev.key === 'Delete' || ev.key === 'Backspace') {
      ev.preventDefault();
      if (e.sel.kind === 'node') ed.removeNode(e.sel.id);
      else if (e.sel.kind === 'edge') ed.removeEdge(e.sel.id, 'key');
    }
  };

  return (
    <div className={styles.ge} onKeyDown={onKey}>
      <Bar mine={ed.mine} current={g.id} />
      <Counts ed={ed} />
      <div className={styles.work}>
        <Palette g={g} s={s} v={v} onAdd={(c) => ed.addNode(c)} />
        <section className={`${styles.gcard} ${styles.cv}`}>
          <ReactFlowProvider>
            <Canvas
              graphId={g.id}
              s={s}
              v={v}
              sel={e.sel}
              label={`${g.name} 그래프 캔버스`}
              onSelect={ed.select}
              onAdd={(c, p) => ed.addNode(c, p)}
              onMove={ed.moveNode}
              onConnect={ed.addEdge}
              onRemove={ed.removeNode}
            />
          </ReactFlowProvider>
        </section>
        <Inspector s={s} v={v} onName={ed.nameEdge} onRemoveEdge={ed.removeEdge} />
      </div>
      {e.modal === 'test' && <TestDialog g={g} v={v} />}
      {e.modal === 'save' && <SaveDialog g={g} s={s} v={v} onSave={ed.save} />}
      {e.modal === 'settings' && (
        <SettingsDialog s={s} D={D} onField={ed.setField} onConfirm={ed.confirmField} />
      )}
      {toastLine}
    </div>
  );
}

/** 위쪽 줄 — 그래프 고르기 · 새 그래프 · 시험해 보기 · 저장 */
function Bar({ mine, current }: { mine: GraphEntry[]; current?: string }) {
  const creating = editor.get().creating;
  return (
    <div className={styles.bar}>
      <h2>상태 그래프 만들기</h2>
      <div className={styles.gsel}>
        <label className={styles.lbl} htmlFor="ge-graph">
          그래프
        </label>
        <select
          id="ge-graph"
          value={current ?? ''}
          onChange={(ev) =>
            editor.set({ current: ev.target.value, sel: { kind: 'none' }, creating: false, menu: false })
          }
        >
          {mine.map((x) => (
            <option key={x.id} value={x.id}>
              {x.name} · {x.id}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={`${styles.gbtn} ${styles.sm}`}
          onClick={() => editor.set({ creating: true, newG: null, menu: false })}
        >
          ＋ 새 그래프
        </button>
      </div>
      {!creating && mine.length > 0 && (
        <div className={`${styles.row} ${styles.right}`}>
          <button type="button" className={styles.gbtn} onClick={() => editor.set({ modal: 'test' })}>
            시험해 보기
          </button>
          <button
            type="button"
            className={`${styles.gbtn} ${styles.pri}`}
            onClick={() => editor.set({ modal: 'save' })}
          >
            저장
          </button>
        </div>
      )}
    </div>
  );
}

/** 진행 줄 — 상태 · 화살표 수, 이름 없는 화살표로 차례로, 승인본 번호, ⋯ 더보기 */
function Counts({ ed }: { ed: ReturnType<typeof useGraphEditor> }) {
  const menuRef = useRef<HTMLDivElement>(null);
  const { e, g, s, v } = ed;
  useEffect(() => {
    if (!e.menu) return;
    const out = (ev: MouseEvent) => {
      if (!menuRef.current?.contains(ev.target as Node)) editor.set({ menu: false });
    };
    document.addEventListener('click', out);
    return () => document.removeEventListener('click', out);
  }, [e.menu]);
  if (!g || !s || !v) return null;
  const w = v.workEdges();
  const named = w.filter((x) => x.name).length;
  const noname = w.length - named;
  const resetLabel = g.draft
    ? '저장본으로 되돌리기'
    : g.k.transitions.length
      ? '확인된 그래프로 되돌리기'
      : '캔버스 비우기';
  return (
    <div className={styles.prog}>
      <span>
        상태 <b>{v.placed().length}</b>개 · 화살표 <b>{w.length}</b>개 (이름 확정 <b>{named}</b> ·{' '}
        <button
          type="button"
          className={styles.need}
          disabled={!noname}
          title={noname ? '누르면 이름 없는 화살표로 차례로 이동' : ''}
          onClick={ed.nextUnnamed}
        >
          이름 없음 {noname}
        </button>
        )
      </span>
      {s.saved && <span className={`${styles.st} ${styles.stGood}`}>승인본 v{s.saved.v}</span>}
      <div className={styles.more} ref={menuRef}>
        <button
          type="button"
          className={`${styles.gbtn} ${styles.sm}`}
          aria-haspopup="true"
          aria-expanded={e.menu}
          onClick={() => editor.set({ menu: !e.menu })}
        >
          ⋯ 더보기
        </button>
        {e.menu && (
          <div className={styles.menu} role="menu">
            <button
              type="button"
              role="menuitem"
              onClick={() => editor.set({ menu: false, modal: 'settings' })}
            >
              그래프 설정 (상태 필드)
            </button>
            <hr />
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                editor.set({ menu: false });
                ed.reset();
              }}
            >
              {resetLabel}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/** 새 그래프 — 아직 그래프로 안 만든 공통코드 그룹을 골라 빈 캔버스를 연다 */
function CreateCard({
  D,
  dom,
  all,
  toast,
}: {
  D: Data;
  dom: string;
  all: GraphEntry[];
  toast: (m: string) => void;
}) {
  const free = freeGroups(all, D.codes);
  const cancel = () => editor.set({ creating: false, newG: null });
  const N = editor.get().newG ?? {
    cg: free[0]?.id ?? '',
    name: free[0] ? nameOf(free[0]) : '',
    entity: '',
  };
  const setN = (patch: Partial<typeof N>) => editor.set({ newG: { ...N, ...patch } });
  if (!free.length)
    return (
      <section className={`${styles.gcard} ${styles.emptyst}`}>
        <span className={`${styles.st} ${styles.stExt}`}>새 그래프</span>
        <h3>그래프로 아직 안 만든 공통코드 그룹이 없습니다</h3>
        <p className={styles.note} style={{ maxWidth: '66ch' }}>
          지금 받은 공통코드 그룹({D.codes.map((c) => c.id).join(' · ') || '없음'})은 모두 그래프가 있습니다.
          공통코드 테이블 export(<span className={styles.mono}>data/codes/common_codes.csv</span>)에 그룹을
          추가하고 화면 데이터를 다시 만들면 여기에 나타납니다 (서버로 열었다면 새로고침).
        </p>
        <button type="button" className={styles.gbtn} onClick={cancel}>
          돌아가기
        </button>
      </section>
    );
  const cg = free.find((x) => x.id === N.cg);
  const guess = cg ? guessField({ graph: {}, code_group: cg }, D.ops) : null;
  const order = cg ? (cg.order.length ? cg.order : Object.keys(cg.codes)) : [];
  return (
    <section className={`${styles.gcard} ${styles.form}`} style={{ maxWidth: 640 }}>
      <h3>새 그래프</h3>
      <div className={styles.fld}>
        <label htmlFor="ge-ncg">공통코드 그룹 — 아직 그래프로 안 만든 것</label>
        <select
          id="ge-ncg"
          value={N.cg}
          onChange={(ev) => {
            const next = free.find((x) => x.id === ev.target.value)!;
            setN({ cg: next.id, name: nameOf(next) });
          }}
        >
          {free.map((c) => (
            <option key={c.id} value={c.id}>
              {c.id} · {c.name} · {Object.keys(c.codes).length}개
            </option>
          ))}
        </select>
        {cg && (
          <span className={styles.hint}>
            {order
              .slice(0, 12)
              .map((c) => `${c} ${cg.codes[c]}`)
              .join(' · ')}
            {Object.keys(cg.codes).length > 12 ? ' …' : ''}
          </span>
        )}
      </div>
      <div className={styles.two}>
        <div className={styles.fld}>
          <label htmlFor="ge-nname">그래프 이름</label>
          <input
            type="text"
            id="ge-nname"
            value={N.name}
            onChange={(ev) => setN({ name: ev.target.value })}
          />
        </div>
        <div className={styles.fld}>
          <label htmlFor="ge-nent">상태를 가진 대상</label>
          <input
            type="text"
            id="ge-nent"
            value={N.entity}
            placeholder="예: 판매상품, 주문"
            onChange={(ev) => setN({ entity: ev.target.value })}
          />
        </div>
      </div>
      <div className={styles.fld}>
        <label htmlFor="ge-ndom">담당 도메인 — 상태 코드 그룹의 주인</label>
        <input type="text" id="ge-ndom" value={`${DOMS[dom] ?? dom} (${dom})`} readOnly />
      </div>
      <div className={styles.box}>
        <b>조회 결과에서 상태를 읽는 필드 (자동 추정)</b>
        <p className={styles.ev}>
          {guess?.v ? (
            <>
              <span className={styles.mono}>{guess.v}</span> — {guess.why}
            </>
          ) : (
            `못 찾았습니다 — ${guess?.why ?? ''}. 만든 뒤 '그래프 설정'에서 고르세요.`
          )}
        </p>
      </div>
      <div className={styles.row}>
        <button
          type="button"
          className={`${styles.gbtn} ${styles.pri}`}
          onClick={() => createGraph(D, dom, N.cg, N.name, N.entity, toast)}
        >
          만들기
        </button>
        <button type="button" className={`${styles.gbtn} ${styles.ghost}`} onClick={cancel}>
          취소
        </button>
      </div>
    </section>
  );
}
