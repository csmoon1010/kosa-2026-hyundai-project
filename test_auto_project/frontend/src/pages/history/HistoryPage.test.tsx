import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import type { Schemas } from '../../api/client';
import { renderWithApp } from '../../test/render';
import { server } from '../../test/server';
import { runs } from '../run/fixtures';
import HistoryPage from './HistoryPage';
import { historyFilter } from './historyFilter';

const serve = (list: Schemas['Run'][]) =>
  server.use(http.get('/api/history/runs', () => HttpResponse.json({ runs: list })));

afterEach(() => historyFilter.reset());

describe('실행 이력', () => {
  it('이력이 없으면 안내', async () => {
    serve([]);
    renderWithApp(<HistoryPage />);
    expect(
      await screen.findByText('실행 이력이 없습니다. 실행 메뉴에서 드라이런을 하면 여기에 남습니다.'),
    ).toBeInTheDocument();
  });

  it('이력 표 · 행 펼치기(호출 · 되돌리는 순서) · 키보드', async () => {
    serve(runs());
    renderWithApp(<HistoryPage />);
    expect(await screen.findByText('총 1건 · 드라이런 1 · 실행 0 (실행기 연결 전)')).toBeInTheDocument();
    const row = screen.getByRole('row', { expanded: false });
    expect(row).toHaveTextContent('배송완료 취소');
    expect(row).toHaveTextContent('드라이런');
    const cells = row.querySelectorAll('td');
    expect([cells[2]!.textContent, cells[3]!.textContent, cells[4]!.textContent]).toEqual(['2', '4', '25']);

    const user = userEvent.setup();
    await user.click(row);
    expect(screen.getByText('배송완료 취소 #2 배송완료취소')).toBeInTheDocument();
    expect(
      screen.getByText(
        '되돌리는 순서: 배송완료 취소 #2 배송완료취소 → 되돌리는 화살표 있음 · 배송완료 취소 #1 배송완료취소 → 되돌리는 화살표 있음',
      ),
    ).toBeInTheDocument();
    row.focus();
    await user.keyboard('{Enter}');
    expect(screen.queryByText(/되돌리는 순서/)).not.toBeInTheDocument();
  });

  it('검색 · 종류 필터', async () => {
    serve(runs());
    renderWithApp(<HistoryPage />);
    const user = userEvent.setup();
    await screen.findByText(/총 1건/);
    await user.selectOptions(screen.getByLabelText('종류 필터'), '실행');
    expect(screen.getByText('조건에 맞는 이력이 없습니다.')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('종류 필터'), '');
    await user.type(screen.getByLabelText('실행 이력 검색'), '배송완료');
    expect(screen.getByRole('row', { expanded: false })).toBeInTheDocument();
    await user.clear(screen.getByLabelText('실행 이력 검색'));
    await user.type(screen.getByLabelText('실행 이력 검색'), '없음');
    expect(screen.getByText('조건에 맞는 이력이 없습니다.')).toBeInTheDocument();
  });
});
