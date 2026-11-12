// 메뉴별 조회 · 저장 훅 (TanStack Query). 저장 뒤에는 관련 쿼리를 다시 불러온다 (docs/react.md 8.1).
import { useQuery } from '@tanstack/react-query';

import { get, type Schemas } from './client';

export const keys = {
  health: ['common', 'health'] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: ({ signal }) => get<Schemas['Health']>('/api/common/health', signal),
    retry: false,
    refetchOnWindowFocus: false,
  });
}
