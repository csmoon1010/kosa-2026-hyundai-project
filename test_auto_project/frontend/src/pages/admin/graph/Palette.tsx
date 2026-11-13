import { useStore } from '../../../lib/store';
import { PALETTE_TYPE } from './Canvas';
import type { GraphEntry, GState, View } from './editorModel';
import { editor } from './editorStore';
import styles from './graph.module.css';

/** 공통코드 — 끌어다 캔버스에 놓거나 누르면 빈 자리에. 이미 놓은 것은 누르면 선택 */
export function Palette({
  g,
  s,
  v,
  onAdd,
}: {
  g: GraphEntry;
  s: GState;
  v: View;
  onAdd: (c: string) => void;
}) {
  const { filter } = useStore(editor);
  const f = filter.trim();
  const list = v.CODES.filter(([c, n]) => !f || c.includes(f) || n.includes(f));
  return (
    <aside className={`${styles.gcard} ${styles.pal}`} aria-label="공통코드">
      <h3>
        {g.name}{' '}
        <span className={styles.mono} style={{ fontWeight: 400, color: 'var(--muted)', fontSize: 12 }}>
          ({g.k.code_group?.id})
        </span>{' '}
        · {v.CODES.length}개
      </h3>
      <input
        type="search"
        placeholder="코드 · 이름 찾기"
        aria-label="공통코드 찾기"
        value={filter}
        onChange={(e) => editor.set({ filter: e.target.value })}
      />
      <div className={styles.plist}>
        {list.length ? (
          list.map(([c, n]) => {
            const on = Boolean(s.nodes[c]);
            return (
              <button
                key={c}
                type="button"
                className={`${styles.pitem} ${on ? styles.placed : ''}`}
                title={on ? '캔버스에 있음 — 누르면 선택' : '끌어다 놓거나 누르면 추가'}
                aria-label={`${c} ${n}${on ? ' · 배치됨' : ''}`}
                draggable={!on}
                onDragStart={(e) => {
                  e.dataTransfer.setData(PALETTE_TYPE, c);
                  e.dataTransfer.effectAllowed = 'move';
                }}
                onClick={() => onAdd(c)}
              >
                <span className={styles.mono}>{c}</span>
                <span>{n}</span>
                {on ? <span className={styles.note}>배치됨</span> : <span />}
              </button>
            );
          })
        ) : (
          <p className={styles.note}>찾는 코드가 없습니다.</p>
        )}
      </div>
    </aside>
  );
}
