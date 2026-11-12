// 메뉴별 조회 · 저장 훅 (TanStack Query). 저장 뒤에는 관련 쿼리를 다시 불러온다 (docs/react.md 8.1).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';

import { del, get, type Schemas } from './client';

export const keys = {
  health: ['common', 'health'] as const,
  scenarios: ['register', 'scenarios'] as const,
  scenario: (id: string) => ['register', 'scenarios', id] as const,
  part: (name: string) => ['admin', 'part', name] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: ({ signal }) => get<Schemas['Health']>('/api/common/health', signal),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

// ─── 시나리오 등록 ───────────────────────────────────────────────────────────────

export function useRegisteredScenarios() {
  return useQuery({
    queryKey: keys.scenarios,
    queryFn: ({ signal }) => get<Schemas['ScenarioList']>('/api/register/scenarios', signal),
    select: (data) => data.scenarios,
  });
}

export function useRegisteredRecord(id: string | null) {
  return useQuery({
    queryKey: keys.scenario(id ?? ''),
    queryFn: ({ signal }) =>
      get<Schemas['RegisteredRecord']>('/api/register/scenarios/' + encodeURIComponent(id ?? ''), signal),
    enabled: Boolean(id),
    staleTime: Infinity, // 등록 기록은 바뀌지 않는다 (지우면 목록에서 빠진다)
  });
}

export function useDeleteScenario() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => del<Schemas['Ok']>('/api/register/scenarios/' + encodeURIComponent(id)),
    onSuccess: (_, id) => {
      client.removeQueries({ queryKey: keys.scenario(id) });
      return client.invalidateQueries({ queryKey: keys.scenarios, exact: true });
    },
  });
}

/** 등록 뒤 목록을 다시 불러온다 (등록은 진행 상태와 같이 움직여서 flow 에서 부른다) */
export function useRefreshScenarios() {
  const client = useQueryClient();
  return useCallback(() => client.invalidateQueries({ queryKey: keys.scenarios, exact: true }), [client]);
}

// ─── 화면 데이터 (관리자 API 를 나눠 받는다) ─────────────────────────────────────────

export function useOperations() {
  return useQuery({
    queryKey: keys.part('operations'),
    queryFn: ({ signal }) => get<Schemas['OperationsPart']>('/api/admin/operations', signal),
    staleTime: 5 * 60_000,
  });
}

export function useEnvironment() {
  return useQuery({
    queryKey: keys.part('environment'),
    queryFn: ({ signal }) => get<Schemas['EnvironmentPart']>('/api/admin/environment', signal),
    staleTime: 60_000,
  });
}

/** (api_id, 필드) → 명세의 한글 이름. 없으면 '' — 입력값 표의 '필드설명' */
export function useFieldLabel() {
  const { data } = useOperations();
  return useCallback(
    (apiId: string, field: string) => {
      const op = data?.ops.find((o) => o.id === apiId);
      const row = op?.req.find((f) => f[0] === field);
      return row?.[1] || '';
    },
    [data],
  );
}
