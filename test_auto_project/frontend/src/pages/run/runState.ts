// 시나리오 실행 — 담은 시나리오 · 반복 횟수 · 이번 실행 확인 · 드라이런 결과. 화면 밖에 두어 메뉴를 옮겨도 남는다.
// 실행기 연결 전이라 드라이런만: API 를 부르지 않고 IR 로 요청(Baseline 에 입력값을 덮은 XML)을 만들어 실행 이력(data/runs)에.
// 되돌릴 수 없는 단계(R2)는 승인본과 별개로 실행할 때마다 확인한다 — 서버가 다시 확인 (POST /api/run/dry-run).
import { post, type Schemas } from '../../api/client';
import { createStore } from '../../lib/store';

type Registered = Schemas['RegisteredSummary'];
export type Run = Schemas['Run'];

export interface RunRow {
  key: string;
  id: string;
  n: number;
}

export interface RunState {
  search: string;
  rows: RunRow[];
  /** 행 key → 이번 실행에서 되돌릴 수 없는 단계를 확인했는가 */
  confirm: Record<string, boolean>;
  result: Run | null;
  error: string | null;
  busy: boolean;
}

export const runState = createStore<RunState>(() => ({
  search: '',
  rows: [],
  confirm: {},
  result: null,
  error: null,
  busy: false,
}));

let seq = 0;
export const MAX_REPEAT = 20;

/** 되돌릴 수 없는 단계가 있어 실행할 때마다 확인해야 하는가 */
export const needsConfirm = (s: Registered | undefined) => Boolean(s && s.confirm_steps.length > 0);

export function pick(id: string) {
  runState.set((s) => ({ rows: [...s.rows, { key: `r${++seq}`, id, n: 1 }], result: null, error: null }));
}

export function remove(key: string) {
  runState.set((s) => {
    const confirm = { ...s.confirm };
    delete confirm[key];
    return { rows: s.rows.filter((r) => r.key !== key), confirm, result: null, error: null };
  });
}

/** 반복 횟수 — 1 ~ 20 으로 맞춘 값을 돌려준다 */
export function setRepeat(key: string, value: string): number {
  const n = Math.max(1, Math.min(MAX_REPEAT, parseInt(value, 10) || 1));
  runState.set((s) => ({ rows: s.rows.map((r) => (r.key === key ? { ...r, n } : r)), result: null }));
  return n;
}

export function setConfirm(key: string, on: boolean) {
  runState.set((s) => ({ confirm: { ...s.confirm, [key]: on } }));
}

/** 드라이런할 수 있는가 — 담은 것이 있고, 모두 등록돼 있고, 재승인 필요가 없고, 확인할 것은 확인했다 */
export function isReady(
  s: RunState,
  regOf: (id: string) => Registered | undefined,
  isStale: (r: Registered) => boolean,
) {
  return (
    s.rows.length > 0 &&
    s.rows.every((r) => {
      const reg = regOf(r.id);
      return Boolean(reg) && !isStale(reg!) && (!needsConfirm(reg) || Boolean(s.confirm[r.key]));
    })
  );
}

/** 드라이런 — 성공하면 결과를 두고 확인은 비운다 (다음 실행에서 다시 확인). 성공하면 true */
export async function dryRun(regOf: (id: string) => Registered | undefined): Promise<boolean> {
  const s = runState.get();
  if (s.busy) return false;
  runState.set({ busy: true, error: null, result: null });
  const items = s.rows.map((r) => {
    const reg = regOf(r.id);
    return {
      id: r.id,
      n: r.n,
      confirm: needsConfirm(reg) && s.confirm[r.key] ? reg!.confirm_steps.map((c) => c.key) : [],
    };
  });
  try {
    const j = await post<Schemas['RunResult']>('/api/run/dry-run', { items });
    runState.set({ result: j.run, confirm: {}, busy: false });
    return true;
  } catch (error) {
    runState.set({ error: '드라이런을 하지 못했어요: ' + (error as Error).message, busy: false });
    return false;
  }
}
