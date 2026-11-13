import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { AppRoutes } from './App';
import { renderWithApp } from './test/render';
import { server } from './test/server';

describe('레이아웃 · 메뉴', () => {
  it('메뉴 5개, 처음은 시나리오 등록, 서버 연결을 확인한다', async () => {
    renderWithApp(<AppRoutes />);
    const nav = screen.getByRole('navigation', { name: '메뉴' });
    const links = Array.from(nav.querySelectorAll('a')).map((a) => a.textContent);
    expect(links).toEqual([
      '시나리오 등록',
      '시나리오 등록(확인용)',
      '시나리오 실행',
      '실행 이력',
      '관리자 메뉴',
    ]);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('시나리오 등록');
    expect(screen.getByRole('link', { name: '시나리오 등록' })).toHaveAttribute('aria-current', 'page');
    expect(await screen.findByText('서버 연결됨')).toBeInTheDocument();
  });

  it('메뉴를 누르면 주소 · 제목이 바뀐다', async () => {
    renderWithApp(<AppRoutes />);
    await userEvent.click(screen.getByRole('link', { name: '실행 이력' }));
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('실행 이력');
    expect(screen.getByRole('link', { name: '실행 이력' })).toHaveAttribute('aria-current', 'page');
  });

  it('관리자는 범위가 주소에 — /admin 은 전사로', () => {
    renderWithApp(<AppRoutes />, '/admin');
    expect(screen.getByRole('tab', { name: /전사/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('link', { name: '관리자 메뉴' })).toHaveAttribute('aria-current', 'page');
  });

  it('가짜 LLM 으로 띄운 서버면 표시한다', async () => {
    server.use(http.get('/api/common/health', () => HttpResponse.json({ ok: true, fake_llm: true })));
    renderWithApp(<AppRoutes />);
    expect(await screen.findByText('가짜 LLM')).toBeInTheDocument();
  });

  it('서버가 없으면 표시한다', async () => {
    server.use(http.get('/api/common/health', () => HttpResponse.error()));
    renderWithApp(<AppRoutes />, '/run');
    expect(await screen.findByText('서버 없음')).toBeInTheDocument();
  });
});
