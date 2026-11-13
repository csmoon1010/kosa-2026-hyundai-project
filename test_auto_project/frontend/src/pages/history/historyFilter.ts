import { createStore } from '../../lib/store';

/** 실행 이력 검색 · 종류 · 펼친 행 — 메뉴를 옮겨도 남는다 (예전 화면과 같다) */
export const historyFilter = createStore(() => ({ search: '', kind: '', open: null as string | null }));
