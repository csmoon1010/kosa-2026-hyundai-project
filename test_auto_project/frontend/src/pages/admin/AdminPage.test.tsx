import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { AppRoutes } from '../../App';
import { renderWithApp } from '../../test/render';
import { server } from '../../test/server';
import { admin, adminHandlers } from './fixtures';

function fakeServer() {
  const sent = {
    rules: [] as unknown[],
    deleted: [] as string[],
    build: 0,
    baselines: [] as unknown[],
    refresh: 0,
  };
  server.use(
    http.post('/api/admin/rules', async ({ request }) => {
      sent.rules.push(await request.json());
      return HttpResponse.json({ build: { catalog_version: 4 } });
    }),
    http.delete('/api/admin/rules/:id', ({ params }) => {
      sent.deleted.push(String(params.id));
      return HttpResponse.json({ build: { catalog_version: 4 } });
    }),
    http.post('/api/admin/build', () => {
      sent.build += 1;
      return HttpResponse.json({ build: { catalog_version: 3 }, changed: false });
    }),
    http.put('/api/admin/preprocessing/baselines', async ({ request }) => {
      sent.baselines.push(await request.json());
      return HttpResponse.json({ file: 'data/out/parameters/baselines/user/x.json' });
    }),
    http.post('/api/admin/preprocessing/refresh', () => {
      sent.refresh += 1;
      return HttpResponse.json({});
    }),
    ...adminHandlers(),
  );
  return sent;
}

const d = admin();

describe('관리자 메뉴 — 전사', () => {
  it('1단계 산출물 · 도메인별 현황 · 명세 소스 · 환경, 도메인 이름을 누르면 그 도메인으로', async () => {
    fakeServer();
    renderWithApp(<AppRoutes />, '/admin/all');
    expect(await screen.findByRole('heading', { name: '1단계 산출물 · 검수 목록' })).toBeInTheDocument();
    expect(
      screen.getByText(
        `${d.environment.build.operations}개 (쓰기 ${d.environment.build.kinds.write}개 · 조회 ${d.environment.build.kinds.read}개)`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`^검수 대기 ${d.review.review.length}건`))).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '도메인별 추출 결과' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Swagger 명세 소스' })).toBeInTheDocument();
    expect(screen.getByText(/쓰기 API \d+개 모두 승인 필수/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '테스트 데이터 전체 정리' })).toBeDisabled();
    // 범위 막대의 작은 글씨 — 그래프 · API 수
    expect(within(screen.getByRole('tab', { name: /물류/ })).getByText(/API \d+/)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '물류 · ds' }));
    expect(screen.getByRole('tab', { name: /물류/ })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByRole('heading', { name: 'Baseline Request · 물류' })).toBeInTheDocument();
  });

  it('전체 변경 확인 = 다시 빌드 → 알림', async () => {
    const sent = fakeServer();
    renderWithApp(<AppRoutes />, '/admin/all');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: '전체 변경 확인' }));
    expect(await screen.findByText('바뀐 것 없음 — catalog v3.')).toBeInTheDocument();
    expect(sent.build).toBe(1);
  });

  it('데이터 조회 — 8종 타일, 팝업에서 문서를 오가고 전처리 문서는 필터로 거른다', async () => {
    fakeServer();
    renderWithApp(<AppRoutes />, '/admin/all');
    const user = userEvent.setup();
    const tile = await screen.findByRole('button', { name: /API Catalog/ });
    expect(tile).toHaveTextContent(
      `API ${d.metadata.metadata.length}개 · catalog v${d.environment.build.catalog_version}`,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Canonical Schema/ })).toHaveTextContent('API 2개'),
    );
    await user.click(tile);
    const dialog = screen.getByRole('dialog', { name: 'API Catalog' });
    expect(within(dialog).getByText('데이터 조회 · 전사')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '닫기' })).toHaveFocus();
    await user.click(within(dialog).getByRole('tab', { name: '3 Canonical Schema' }));
    expect(within(dialog).getByRole('heading', { name: 'Canonical Schema', level: 2 })).toBeInTheDocument();
    expect(within(dialog).getByRole('status')).toHaveTextContent(/^API 2개 · 필드 \d+개$/);
    await user.selectOptions(
      within(dialog).getByLabelText('api_id 필터'),
      'hshop-openapi:POST:/sc/scb/scbd/multiOshpProcess.do',
    );
    expect(within(dialog).getByRole('status')).toHaveTextContent(/^API 1개/);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(tile).toHaveFocus(); // 연 자리로
  });

  it('규칙 입력(전사) — 검증 실패면 적용 거부, 통과하면 저장 · 다시 빌드', async () => {
    const sent = fakeServer();
    renderWithApp(<AppRoutes />, '/admin/all');
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: '규칙 입력' });
    await user.selectOptions(screen.getByLabelText('항목'), 'value');
    const body = screen.getByLabelText('값 해석');
    await user.type(body, '01');
    await user.click(screen.getByRole('button', { name: '저장 · 적용' }));
    expect(screen.getByRole('alert')).toHaveTextContent('적용 거부검증을 통과하지 못했습니다.');
    expect(
      screen.getByText('「코드 뜻 · 코드 뜻」 형식이어야 한다 (예: 04 새벽배송 · 05 정기배송)'),
    ).toBeInTheDocument();
    expect(sent.rules).toEqual([]);

    await user.clear(body);
    await user.type(body, '01 단건배송 · 02 분할배송');
    await user.click(screen.getByRole('button', { name: '저장 · 적용' }));
    expect(
      await screen.findByText(
        'Parameter KB · 값 해석 저장 — data/config/rules.ui.yaml (이 값을 쓰는 단계는 아직 없음)',
      ),
    ).toBeInTheDocument();
    expect(sent.rules).toEqual([
      {
        place: 'am',
        doc: 'pkb',
        item: 'value',
        dom: null,
        target: (screen.getByLabelText('대상 필드') as HTMLSelectElement).value,
        body: '01 단건배송 · 02 분할배송',
      },
    ]);
    expect(body).toHaveValue('');
  });
});

describe('관리자 메뉴 — 도메인', () => {
  it('규칙 입력(도메인) — 구분값은 그 API 의 요청 필드인지 본다, 등록된 내역에 overrides.yaml', async () => {
    const sent = fakeServer();
    renderWithApp(<AppRoutes />, '/admin/logistics');
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: '규칙 입력' });
    await user.selectOptions(screen.getByLabelText('저장 대상'), 'meta');
    await user.selectOptions(screen.getByLabelText('항목'), 'sel');
    await user.selectOptions(
      screen.getByLabelText('대상 API'),
      'hshop-openapi:POST:/sc/scb/scbd/multiOshpBackProcess.do',
    );
    await user.type(screen.getByLabelText('구분값'), 'nope: X 없음');
    await user.click(screen.getByRole('button', { name: '저장 · 적용' }));
    expect(screen.getByText('nope 는 이 API 의 요청 필드가 아니다')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('구분값'));
    await user.type(screen.getByLabelText('구분값'), 'procGb: PB3 배송완료취소');
    await user.click(screen.getByRole('button', { name: '저장 · 적용' }));
    await screen.findByText(/API MetaData · 구분값 저장 — .* 다시 빌드 \(catalog v4\)/);
    expect(sent.rules[0]).toMatchObject({ place: 'ov', doc: 'meta', item: 'sel', dom: 'logistics' });

    await user.click(screen.getByRole('button', { name: /^등록된 내역 \(\d+\)$/ }));
    const dialog = screen.getByRole('dialog', { name: '등록된 내역' });
    expect(within(dialog).getByText('규칙 입력 · 물류')).toBeInTheDocument();
    expect(within(dialog).getAllByText(/overrides\.yaml · 사람 편집/).length).toBeGreaterThan(0);
  });

  it('화면에서 넣은 규칙은 등록된 내역에서 지운다', async () => {
    const sent = fakeServer();
    renderWithApp(<AppRoutes />, '/admin/goods');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /^등록된 내역 \(1\)$/ }));
    const dialog = screen.getByRole('dialog', { name: '등록된 내역' });
    await user.click(within(dialog).getByRole('button', { name: '삭제' }));
    await waitFor(() => expect(sent.deleted).toEqual([String(d.rules.rules[0]!.id)]));
    expect(await screen.findByText('규칙을 지우고 다시 빌드했습니다.')).toBeInTheDocument();
  });

  it('Baseline Request — parameter_path 별 값을 사용자 등록 (전처리 Baseline)', async () => {
    const sent = fakeServer();
    renderWithApp(<AppRoutes />, '/admin/logistics');
    const user = userEvent.setup();
    const select = await screen.findByLabelText('대상 엔드포인트');
    expect(within(select).getAllByRole('option')).toHaveLength(2);
    const body = screen.getByLabelText('기본 요청값 · parameter_path별 JSON');
    expect(JSON.parse((body as HTMLTextAreaElement).value)).toEqual(expect.any(Object));
    fireEvent.change(body, { target: { value: '{ 망가진' } });
    await user.click(screen.getByRole('button', { name: '사용자 등록 · 검증' }));
    expect(await screen.findByText(/^저장 실패: /)).toBeInTheDocument();
    expect(sent.baselines).toEqual([]);

    fireEvent.change(body, { target: { value: '{"$.body.data1.data2.data3.venCd": "001442"}' } });
    await user.click(screen.getByRole('button', { name: '사용자 등록 · 검증' }));
    expect(
      await screen.findByText('사용자 등록값 저장 · data/out/parameters/baselines/user/x.json'),
    ).toBeInTheDocument();
    expect(sent.baselines).toEqual([
      {
        selected_api_id: (select as HTMLSelectElement).value,
        values: { '$.body.data1.data2.data3.venCd': '001442' },
      },
    ]);
  });
});

describe('머리 — 전처리 산출물 갱신 (혜정)', () => {
  it('상태 줄 · 갱신 · 실패 문구', async () => {
    const sent = fakeServer();
    renderWithApp(<AppRoutes />, '/register');
    expect(
      await screen.findByText('전처리 JSON · Canonical 43 · KB 43 · Baseline 43 · 응답 43'),
    ).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '전처리 산출물 갱신' }));
    await waitFor(() => expect(sent.refresh).toBe(1));
    server.use(
      http.post('/api/admin/preprocessing/refresh', () =>
        HttpResponse.json({ error: '산출물 폴더가 없습니다' }, { status: 500 }),
      ),
    );
    await user.click(screen.getByRole('button', { name: '전처리 산출물 갱신' }));
    expect(await screen.findByText('갱신 실패: 산출물 폴더가 없습니다')).toBeInTheDocument();
  });
});
