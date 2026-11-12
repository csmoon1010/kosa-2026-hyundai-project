import { useContext, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { PageActionsSlot } from './pageActionsSlot';

/** 머리 오른쪽에 버튼을 넣는다 (예: 확인용의 '＋ 새 시나리오 등록') */
export function PageActions({ children }: { children: ReactNode }) {
  const slot = useContext(PageActionsSlot);
  return slot ? createPortal(children, slot) : null;
}
