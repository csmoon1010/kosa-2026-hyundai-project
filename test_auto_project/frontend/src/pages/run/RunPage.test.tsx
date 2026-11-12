import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import type { Schemas } from '../../api/client';
import { keys } from '../../api/queries';
import { AppRoutes } from '../../App';
import { renderWithApp } from '../../test/render';
import { server } from '../../test/server';
import { environment } from '../register/fixtures';
import { dryRunResult, runs, scenarios, withR2 } from './fixtures';
import RunPage from './RunPage';
import { runState } from './runState';

function fakeServer(list: Schemas['RegisteredSummary'][], catalog = 3) {
  const sent: unknown[] = [];
  server.use(
    http.get('/api/register/scenarios', () => HttpResponse.json({ scenarios: list })),
    http.get('/api/admin/environment', () => HttpResponse.json(environment(catalog))),
    http.get('/api/admin/operations', () =>
      HttpResponse.json({
        ops: [
          {
            id: 'hshop-openapi:POST:/sc/scb/scbd/selectOshpDtlList.do',
            path: '/sc/scb/scbd/selectOshpDtlList.do',
            sum: '출고조회',
            kind: 'read',
            dom: 'ds',
            req: [['oauserId', '사용자ID', '']],
            res: [],
          },
        ],
      }),
    ),
    http.get('/api/history/runs', () => HttpResponse.json({ runs: runs() })),
    http.post('/api/run/dry-run', async ({ request }) => {
      sent.push(await request.json());
      return HttpResponse.json({ run: dryRunResult() });
    }),
  );
  return { sent };
}

afterEach(() => runState.reset());

describe('시나리오 실행', () => {
  it('등록된 시나리오가 없으면 안내', async () => {
    fakeServer([]);
    renderWithApp(<RunPage />);
    expect(await screen.findByText(/등록된 시나리오가 없습니다. 시나리오 등록에서/)).toBeInTheDocument();
    expect(
      screen.getByText('왼쪽에서 시나리오를 누르면 담깁니다. 아직 등록된 시나리오가 없습니다.'),
    ).toBeInTheDocument();
  });

  it('담기 · 반복 횟수는 1 ~ 20 · 빼기 · 검색', async () => {
    fakeServer(scenarios());
    renderWithApp(<RunPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /배송완료 취소/ }));
    expect(screen.getByText('(1)')).toBeInTheDocument();
    const repeat = screen.getByLabelText('반복 횟수');
    await user.clear(repeat);
    await user.type(repeat, '50');
    await user.tab();
    expect(repeat).toHaveValue('20');
    await user.clear(repeat);
    await user.type(repeat, 'x{Enter}');
    expect(repeat).toHaveValue('1');
    expect(screen.getByRole('button', { name: '드라이런' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: '빼기' }));
    expect(screen.getByText('왼쪽에서 시나리오를 누르면 담깁니다.')).toBeInTheDocument();

    await user.type(screen.getByLabelText('실행 시나리오 검색'), '없는 이름');
    expect(screen.getByText('찾는 시나리오가 없습니다.')).toBeInTheDocument();
  });

  it('되돌릴 수 없는 단계는 이번 실행에서 확인해야 드라이런 — 결과 · 이력 갱신 · 확인은 비운다', async () => {
    const api = fakeServer(withR2());
    const { client } = renderWithApp(<RunPage />);
    client.setQueryData(keys.runs, { runs: [] }); // 이력 화면을 한 번 본 상태
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /배송완료 취소/ }));
    const repeat = screen.getByLabelText('반복 횟수');
    await user.clear(repeat);
    await user.type(repeat, '2{Enter}');

    const dry = screen.getByRole('button', { name: '드라이런' });
    expect(dry).toBeDisabled();
    expect(screen.getByText('R2 1')).toBeInTheDocument();
    const check = screen.getByRole('checkbox', { name: /되돌릴 수 없는 단계를 실행해도 돼요/ });
    expect(screen.getByText('배송완료취소')).toBeInTheDocument();
    await user.click(check);
    expect(dry).toBeEnabled();
    expect(screen.getByRole('button', { name: '실행 (연결 전)' })).toBeDisabled();

    await user.click(dry);
    expect(await screen.findByRole('heading', { name: '드라이런 결과' })).toBeInTheDocument();
    expect(api.sent).toEqual([{ items: [{ id: scenarios()[0]!.id, n: 2, confirm: ['1-1'] }] }]);
    expect(screen.getByText('요청 4건 · 실제 API 는 호출하지 않았어요')).toBeInTheDocument();
    expect(screen.getByText('배송완료 취소 #1')).toBeInTheDocument();
    expect(screen.getByText('배송완료 취소 #2')).toBeInTheDocument();
    expect(screen.getAllByText('보낼 요청 XML')).toHaveLength(2); // 2회째는 서버가 XML 을 다시 싣지 않는다
    expect(screen.getByText(/메모 25개/)).toBeInTheDocument();
    expect(screen.getByText('✓ 실행 이력에 남겼어요')).toBeInTheDocument();
    expect(screen.getAllByText('사용자ID')).toHaveLength(2); // 조회 단계 × 2회 — 필드 한글명
    expect(check).not.toBeChecked(); // 다음 실행에서 다시 확인
    expect(dry).toBeDisabled();
    await waitFor(() => expect(client.getQueryState(keys.runs)?.isInvalidated).toBe(true)); // 이력을 다시 열면 새로 받는다
  });

  it('재승인 필요는 담지 못한다', async () => {
    fakeServer(scenarios(), 4);
    renderWithApp(<RunPage />);
    const item = await screen.findByRole('button', { name: /배송완료 취소/ });
    await waitFor(() => expect(item).toBeDisabled());
    expect(within(item).getByText('· 재승인 필요')).toBeInTheDocument();
  });

  it('서버가 거부하면 그 문구', async () => {
    fakeServer(scenarios());
    server.use(
      http.post('/api/run/dry-run', () =>
        HttpResponse.json({ error: '등록 뒤 API Catalog 가 바뀌었습니다 — 재승인' }, { status: 400 }),
      ),
    );
    renderWithApp(<RunPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /배송완료 취소/ }));
    await user.click(screen.getByRole('button', { name: '드라이런' }));
    expect(
      await screen.findByText('드라이런을 하지 못했어요: 등록 뒤 API Catalog 가 바뀌었습니다 — 재승인'),
    ).toBeInTheDocument();
  });

  it('결과에서 실행 이력으로 — 다른 메뉴로 갔다 와도 담은 것 · 결과가 남는다', async () => {
    fakeServer(scenarios());
    renderWithApp(<AppRoutes />, '/run');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /배송완료 취소/ }));
    await user.click(screen.getByRole('button', { name: '드라이런' }));
    await user.click(await screen.findByRole('button', { name: '실행 이력 보기' }));
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('실행 이력');
    await user.click(screen.getByRole('link', { name: '시나리오 실행' }));
    expect(screen.getByRole('heading', { name: '드라이런 결과' })).toBeInTheDocument();
  });
});
