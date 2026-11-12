const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/preprocessing-ui.js'), 'utf8');

function mount() {
  const elements = new Map();
  const el = id => {
    if (!elements.has(id)) {
      let html = '';
      elements.set(id, { value: '', hidden: true, events: {}, textContent: '',
        get innerHTML() { return html; },
        set innerHTML(value) { html = value; const first = value.match(/<option value="([^"]*)"/); if (first) this.value = first[1]; },
        addEventListener(event, callback) { this.events[event] = callback; }, removeEventListener() {},
        querySelector() { return null; }, replaceChildren() { html = ''; }, append() {},
        insertAdjacentHTML(position, value) { html += value; } });
    }
    return elements.get(id);
  };
  const sid = 'hshop-openapi:POST:/orders/query.do';
  const field = { name: 'venCd', parameter_path: '$.body.data1.venCd', xmlPath: '/Root/row/venCd',
    type: 'string', required: true, requiredDeclared: true, location: 'body', value: '001442', example: '001442' };
  const canonical = { documentId: 'hshop-openapi', apiId: 'POST:/orders/query.do', parameters: [field, { ...field, parameter_path: '$.body.data2.venCd' }] };
  const preprocessed = { canonical_schema: { [sid]: canonical }, parameter_kb: {}, response_outputs: {}, common_knowledge: [],
    baselines: { [sid]: { user_registered: false, parameters: canonical.parameters, example_values: { [field.parameter_path]: '001442' } } },
    counts: { canonical_schema: 1, baseline: 1, parameter_kb: 0, response_outputs: 0 }, warnings: [] };
  const requests = [];
  const ctx = { TAP: { preprocessing: preprocessed, metadata: [{ api_id: sid, domain: 'ds', api_name: '주문조회' }] },
    REAL_DOCS: {}, REAL_DOM: { logistics: 'ds' }, S: { dom: 'logistics' }, DOM_NAME: () => '물류',
    esc: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
    tbl: (headers, rows, empty) => `<table>${headers.join('|')}${rows.length ? rows.join('') : empty}</table>`,
    el, renderBaseline() {}, saveBaseline() {}, openDoc() {}, toast() {},
    document: { activeElement: null, querySelector: () => el('baselineLabel') }, location: { protocol: 'http:' }, window: {},
    api: async (route, body) => { requests.push({ route, body }); return { file: 'data/baselines/preprocessing/test.json' }; },
    rerenderAll: () => ctx.renderBaseline() };
  vm.runInNewContext(source, ctx);
  return { ctx, sid, field, el, requests };
}

test('JSON 화면은 전체 경로·타입·필수여부와 동명 필드를 유지한다', () => {
  const { ctx } = mount();
  const html = ctx.REAL_DOCS.schema('logistics').body;
  assert.match(html, /\$\.body\.data1\.venCd/);
  assert.match(html, /\$\.body\.data2\.venCd/);
  assert.match(html, /\/Root\/row\/venCd/);
  assert.match(html, /string/);
  assert.match(html, /필수/);
});

test('예시 Baseline을 미등록으로 표시하고 저장 시 경로별 값을 전송한다', async () => {
  const { ctx, sid, field, el, requests } = mount();
  assert.equal(el('blStat').value, '예시 초안 · 미등록');
  const values = JSON.parse(el('blBody').value);
  assert.equal(values[field.parameter_path], '001442');
  await ctx.saveBaseline();
  assert.equal(requests[0].route, '/api/preprocessing/baseline');
  assert.equal(requests[0].body.selected_api_id, sid);
  assert.equal(requests[0].body.values[field.parameter_path], '001442');
  await el('refreshPreprocessing').events.click();
  assert.equal(requests[1].route, '/api/preprocessing/refresh');
  assert.equal(el('refreshPreprocessing').disabled, false);
});

test('네 산출물 팝업의 document/api_id 필터와 연동 후보를 적용한다', () => {
  const { ctx, sid, el } = mount();
  const other = 'other-openapi:POST:/orders/other.do';
  ctx.TAP.preprocessing.canonical_schema[other] = {
    documentId: 'other-openapi', apiId: 'POST:/orders/other.do', parameters: [] };
  ctx.TAP.metadata.push({ api_id: other, domain: 'ds', api_name: '다른 API' });
  for (const id of ['schema', 'baseline', 'pkb', 'resp']) {
    ctx.openDoc(id, 'logistics');
    assert.match(el('artifactDocumentFilter').innerHTML, /hshop-openapi/);
    assert.match(el('artifactDocumentFilter').innerHTML, /other-openapi/);
    const api = el('artifactApiFilter');
    api.value = sid;
    api.events.change();
    assert.ok(el('artifactFilteredResults').innerHTML.includes(sid));
    assert.ok(!el('artifactFilteredResults').innerHTML.includes(other));
    const document = el('artifactDocumentFilter');
    document.value = 'other-openapi';
    document.events.change();
    assert.equal(api.value, '');
    assert.ok(api.innerHTML.includes(other));
    assert.ok(!api.innerHTML.includes(sid));
    assert.ok(el('artifactFilteredResults').innerHTML.includes(other));
    assert.ok(!el('artifactFilteredResults').innerHTML.includes(sid));
  }
});

test('도메인 변경 시 document/API 후보를 좁히고 기존 범위 밖 선택은 해제한다', () => {
  const { ctx, sid, el } = mount();
  const product = 'product-openapi:POST:/products/create.do';
  ctx.TAP.preprocessing.canonical_schema[product] = {
    documentId: 'product-openapi', apiId: 'POST:/products/create.do', parameters: [] };
  ctx.TAP.metadata.push({ api_id: product, domain: 'pd', api_name: '상품생성' });
  for (const id of ['schema', 'baseline', 'pkb', 'resp']) {
    ctx.openDoc(id, 'logistics');
    const domain = el('artifactDomainFilter'), document = el('artifactDocumentFilter'), api = el('artifactApiFilter');
    assert.equal(domain.value, 'ds');
    assert.match(domain.innerHTML, /상품 \(pd\)/);
    document.value = 'hshop-openapi'; document.events.change();
    api.value = sid; api.events.change();
    domain.value = 'pd'; domain.events.change();
    assert.equal(document.value, '');
    assert.equal(api.value, '');
    assert.ok(document.innerHTML.includes('product-openapi'));
    assert.ok(!document.innerHTML.includes('hshop-openapi'));
    assert.ok(api.innerHTML.includes(product));
    assert.ok(!api.innerHTML.includes(sid));
    assert.ok(el('artifactFilteredResults').innerHTML.includes(product));
    assert.ok(!el('artifactFilteredResults').innerHTML.includes(sid));
    domain.value = ''; domain.events.change();
    assert.ok(api.innerHTML.includes(product));
    assert.ok(api.innerHTML.includes(sid));
  }
});
