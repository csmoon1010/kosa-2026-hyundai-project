// 혜정 전처리 화면 — 예전 node 테스트(tests/preprocessing-ui.test.cjs)를 React 화면으로 옮긴 것 (2026-11-13, R6)
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { AppRoutes } from '../../../App';
import { renderWithApp } from '../../../test/render';
import { server } from '../../../test/server';
import { admin, adminHandlers } from '../fixtures';

const sid = 'hshop-openapi:POST:/orders/query.do';
const other = 'other-openapi:POST:/orders/other.do';
const product = 'product-openapi:POST:/products/create.do';
const field = {
  name: 'venCd',
  parameter_path: '$.body.data1.venCd',
  xmlPath: '/Root/row/venCd',
  type: 'string',
  required: true,
  requiredDeclared: true,
  location: 'body',
  value: '001442',
  example: '001442',
};

/** 예전 테스트와 같은 산출물 — 같은 이름 필드 두 개(경로만 다름), 예시 Baseline(미등록), 다른 document · 다른 도메인 API */
function data() {
  const d = admin();
  // 견본 JSON 의 타입은 실제 API 이름까지 고정이라 — 바꿔 넣는 칸은 느슨하게
  const pre = d.preprocessing.preprocessing as unknown as Record<string, Record<string, object>>;
  const [baseC] = Object.values(pre.canonical_schema!);
  const [baseB] = Object.values(pre.baselines!);
  const fields = [field, { ...field, parameter_path: '$.body.data2.venCd' }];
  const canon = (documentId: string, apiId: string, parameters: object[]) => ({
    ...baseC,
    documentId,
    apiId,
    parameters,
  });
  pre.canonical_schema = {
    [sid]: canon('hshop-openapi', 'POST:/orders/query.do', fields),
    [other]: canon('other-openapi', 'POST:/orders/other.do', []),
    [product]: canon('product-openapi', 'POST:/products/create.do', []),
  };
  pre.baselines = {
    [sid]: {
      ...baseB,
      user_registered: false,
      parameters: fields,
      example_values: { [field.parameter_path]: '001442' },
    },
  };
  pre.parameter_kb = {};
  pre.response_outputs = {};
  const meta = d.metadata.metadata[0]!;
  d.metadata.metadata.push(
    { ...meta, api_id: sid, domain: 'ds', api_name: '주문조회' },
    { ...meta, api_id: other, domain: 'ds', api_name: '다른 API' },
    { ...meta, api_id: product, domain: 'pd', api_name: '상품생성' },
  );
  return d;
}

async function openDoc(name: RegExp) {
  server.use(...adminHandlers(data()));
  renderWithApp(<AppRoutes />, '/admin/logistics');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name }, { timeout: 5000 }));
  return { user, dialog: await screen.findByRole('dialog') };
}

const DOCS = ['3 Canonical Schema', '5 Baseline Request', '6 Parameter KB', '7 Response Outputs'];
const optionValues = (select: HTMLElement) =>
  within(select)
    .getAllByRole('option')
    .map((o) => (o as HTMLOptionElement).value);

describe('전처리 산출물 화면 (혜정)', { timeout: 20_000 }, () => {
  it('JSON 화면은 전체 경로 · 타입 · 필수여부와 같은 이름 필드를 유지한다', async () => {
    const { dialog } = await openDoc(/Canonical Schema/);
    const text = dialog.textContent ?? '';
    expect(text).toContain('$.body.data1.venCd');
    expect(text).toContain('$.body.data2.venCd');
    expect(text).toContain('/Root/row/venCd');
    expect(text).toContain('string');
    expect(text).toContain('필수');
  });

  it('예시 Baseline 을 미등록으로 보이고 경로별 값을 채운다', async () => {
    server.use(...adminHandlers(data()));
    renderWithApp(<AppRoutes />, '/admin/logistics');
    const user = userEvent.setup();
    const select = await screen.findByLabelText('대상 엔드포인트', {}, { timeout: 5000 });
    await user.selectOptions(select, sid);
    expect(screen.getByLabelText('등록 여부')).toHaveValue('예시 초안 · 미등록');
    const values = JSON.parse(
      (screen.getByLabelText('기본 요청값 · parameter_path별 JSON') as HTMLTextAreaElement).value,
    );
    expect(values[field.parameter_path]).toBe('001442');
  });

  it('네 산출물 팝업의 document / api_id 필터와 연동 후보', async () => {
    const { user, dialog } = await openDoc(/Canonical Schema/);
    for (const doc of DOCS) {
      await user.click(within(dialog).getByRole('tab', { name: doc }));
      const documentF = within(dialog).getByLabelText('document 필터');
      const apiF = within(dialog).getByLabelText('api_id 필터');
      expect(optionValues(documentF)).toEqual(expect.arrayContaining(['hshop-openapi', 'other-openapi']));
      await user.selectOptions(apiF, sid);
      expect(dialog.textContent).toContain(sid);
      expect(dialog.textContent).not.toContain(other);
      await user.selectOptions(documentF, 'other-openapi');
      expect(apiF).toHaveValue('');
      expect(optionValues(apiF)).toContain(other);
      expect(optionValues(apiF)).not.toContain(sid);
      expect(dialog.textContent).toContain(other);
      expect(dialog.textContent).not.toContain(sid);
      await user.selectOptions(documentF, ''); // 다음 문서를 위해 되돌림 (문서마다 따로 기억)
    }
  });

  it('도메인을 바꾸면 document / API 후보를 좁히고 범위 밖 선택은 해제한다', async () => {
    const { user, dialog } = await openDoc(/Canonical Schema/);
    for (const doc of DOCS) {
      await user.click(within(dialog).getByRole('tab', { name: doc }));
      const domainF = within(dialog).getByLabelText('도메인 필터');
      const documentF = within(dialog).getByLabelText('document 필터');
      const apiF = within(dialog).getByLabelText('api_id 필터');
      expect(domainF).toHaveValue('ds');
      expect(within(domainF).getByRole('option', { name: '상품 (pd)' })).toBeInTheDocument();
      await user.selectOptions(documentF, 'hshop-openapi');
      await user.selectOptions(apiF, sid);
      await user.selectOptions(domainF, 'pd');
      expect(documentF).toHaveValue('');
      expect(apiF).toHaveValue('');
      expect(optionValues(documentF)).toContain('product-openapi');
      expect(optionValues(documentF)).not.toContain('hshop-openapi');
      expect(optionValues(apiF)).toContain(product);
      expect(optionValues(apiF)).not.toContain(sid);
      expect(dialog.textContent).toContain(product);
      expect(dialog.textContent).not.toContain(sid);
      await user.selectOptions(domainF, '');
      expect(optionValues(apiF)).toEqual(expect.arrayContaining([product, sid]));
    }
  });
});
