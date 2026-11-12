import { createContext } from 'react';

/** 머리 오른쪽 자리 — 레이아웃이 만들고(Layout), 페이지가 PageActions 로 버튼을 넣는다 */
export const PageActionsSlot = createContext<HTMLElement | null>(null);
