import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';

/** 쿼리 · 라우터를 갖춰 그린다. path 는 처음 주소. client 로 쿼리 상태를 볼 수 있다. */
export function renderWithApp(ui: ReactElement, path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}
