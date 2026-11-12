import type { IrBinding, IrInput } from '../api/ir';
import { useFieldLabel } from '../api/queries';
import styles from './ParamTable.module.css';

/** 단계 입력값 — 표: 필드명 · 필드설명 · 입력값. 필드설명은 명세의 한글 이름(없으면 빈칸) */
export function ParamTable({
  apiId,
  inputs,
  bindings,
}: {
  apiId: string;
  inputs?: IrInput[];
  bindings?: IrBinding[];
}) {
  const labelOf = useFieldLabel();
  const binds = Object.fromEntries((bindings ?? []).map((b) => [b.binding_id, b.from ?? b]));
  if (!inputs?.length) return <div className={styles.empty}>바꿀 입력 없음 — 기본값 그대로</div>;
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>필드명</th>
            <th>필드설명</th>
            <th>입력값</th>
          </tr>
        </thead>
        <tbody>
          {inputs.map((x, i) => (
            <tr key={`${x.field}-${i}`}>
              <td className={styles.field}>{x.field}</td>
              <td>{labelOf(apiId, x.field)}</td>
              <Value input={x} from={x.ref ? binds[x.ref] : undefined} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Value({
  input,
  from,
}: {
  input: IrInput;
  from?: { from_step_id?: string | null; output_name?: string | null };
}) {
  if (input.source === 'fixed') return <td className={styles.value}>{String(input.value ?? '')}</td>;
  if (input.source === 'bind') {
    const n =
      String(from?.from_step_id ?? '')
        .split('-')
        .pop() || '?';
    return (
      <td className={`${styles.value} ${styles.bind}`}>
        단계 {n}의 <span className="mono">{from?.output_name ?? ''}</span>
      </td>
    );
  }
  return <td className={`${styles.value} ${styles.open}`}>정해지지 않음</td>;
}
