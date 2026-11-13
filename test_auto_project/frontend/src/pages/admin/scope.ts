// 관리자 메뉴 범위 — 전사 · 도메인 3개 (1차 범위: 주문 · 상품 · 물류). 화면 주소는 /admin/all · /admin/order …
export const DOMAINS = [
  ['order', '주문', 'od'],
  ['goods', '상품', 'pd'],
  ['logistics', '물류', 'ds'],
] as const;
export type Scope = 'all' | (typeof DOMAINS)[number][0];

export const REAL_DOM: Record<string, string> = Object.fromEntries(DOMAINS.map(([d, , code]) => [d, code]));
export const DOM_LABEL: Record<string, string> = Object.fromEntries(DOMAINS.map(([d, n]) => [d, n]));

/** 도메인 탭에 분류된 API 가 없을 때 */
export const noApi = (dom: string | null) =>
  dom === 'order'
    ? '주문(od)으로 분류된 API 가 없습니다. 주문 상태를 바꾸고 조회하는 출고 · 회수 API 는 물류(ds)로 분류되어 물류 탭에서 다룹니다.'
    : '이 도메인으로 분류된 API 가 없습니다.';
