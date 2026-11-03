const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { validateSelection } = require('../prototype/api-selection-import.js');

const rawExample = JSON.parse(fs.readFileSync(path.join(__dirname, '../prototype/examples/api-selection-installation-product.json'), 'utf8'));
// The editable example has empty API placeholders. Use valid test-only IDs for
// contract tests, without changing the user's source example or import rules.
const example = structuredClone(rawExample);
example.api_selection_results.forEach((row,i)=>{
  row.api_candidates=row.api_candidates.map((id,j)=>id.trim()?id:`TEST_API_${i}_${j}`);
  if(row.selected_api_id==='')row.selected_api_id=row.api_candidates[0];
});
const clone = () => structuredClone(example);

test('유효한 입력의 보류·가선택·미해결과 추가 필드를 변경하지 않는다', () => {
  const input = clone();
  input.extra = { version: 1 };
  const before = JSON.stringify(input);
  assert.equal(validateSelection(input), input);
  assert.equal(JSON.stringify(input), before);
  assert.equal(input.status, '검토 필요');
  assert.equal(input.api_selection_results[4].selected_api_id, null);
  assert.equal(input.api_selection_results.filter(x => x.selection_status === '가선택').length, 3);
  assert.equal(input.unresolved.length, 2);
});

test('단일 업무의 추가 예시와 생략된 unresolved를 허용한다', () => {
  const input = clone();
  input.api_selection_results = [input.api_selection_results[0]];
  delete input.unresolved;
  assert.equal(validateSelection(input), input);
});

test('원본 요청이 없거나 결과가 비어 있으면 거절한다', () => {
  const input = clone();
  input.original_question = '  ';
  assert.throws(() => validateSelection(input), /original_question/);
  input.original_question = '주문을 만들어줘';
  input.api_selection_results = [];
  assert.throws(() => validateSelection(input), /1개 이상/);
  assert.throws(() => validateSelection([]), /최상위/);
});

test('업무·단계 번호 중복을 거절한다', () => {
  const input = clone();
  input.api_selection_results.push(structuredClone(input.api_selection_results[0]));
  assert.throws(() => validateSelection(input), /중복/);
});

test('후보에 없는 선택 API를 거절한다', () => {
  const input = clone();
  input.api_selection_results[0].selected_api_id = '없는 API';
  assert.throws(() => validateSelection(input), /api_candidates에 없습니다/);
});

test('선택된 상태에 null 또는 누락된 API ID가 있으면 거절한다', () => {
  const input = clone();
  input.api_selection_results[0].selected_api_id = null;
  assert.throws(() => validateSelection(input), /null/);
  delete input.api_selection_results[0].selected_api_id;
  assert.throws(() => validateSelection(input), /API ID 또는 null/);
});

test('같은 업무 번호에 다른 도메인이 있으면 거절한다', () => {
  const input = clone();
  input.api_selection_results[1].domain = 'OD';
  assert.throws(() => validateSelection(input), /domain이 서로 다릅니다/);
});

test('미해결 항목이 없는 업무·단계를 참조하면 거절한다', () => {
  const input = clone();
  input.unresolved[0].path_sequence = 99;
  assert.throws(() => validateSelection(input), /path_sequence/);
  input.unresolved[0].path_sequence = 3;
  input.unresolved[0].step = 99;
  assert.throws(() => validateSelection(input), /step/);
});

test('번호와 후보 배열의 타입을 검사한다', () => {
  const input = clone();
  input.api_selection_results[0].step = '1';
  assert.throws(() => validateSelection(input), /정수/);
  input.api_selection_results[0].step = 1;
  input.api_selection_results[0].api_candidates = 'DEMO_PD_CREATE_PRODUCT';
  assert.throws(() => validateSelection(input), /문자열의 배열/);
});


test('구조화된 의도 조건을 보존하고 기존 문자열 조건도 허용한다', () => {
  const { validateIntent } = require('../prototype/api-selection-import.js');
  const input = {original_question:'설치상품 가격을 설정',tasks:[{
    domain:'PD',action:'상품 수정',sequence:1,count:1,
    conditions:[{search_query:'설치상품 구분',value:true},{search_query:'상품 가격',value:50000,unit:'원'}]
  }]};
  assert.equal(validateIntent(input),input);
  assert.equal(input.tasks[0].conditions[1].value,50000);
  input.tasks[0].conditions='설치상품 가격을 설정';assert.equal(validateIntent(input),input);
  for(const invalid of [[],{},[123]]){
    input.tasks[0].conditions=invalid;assert.throws(()=>validateIntent(input),/conditions/);
  }
});

test('빈 API 식별자는 승인된 선택으로 가져오지 않는다',()=>{ const input=clone();input.api_selection_results[0].api_candidates=[''];input.api_selection_results[0].selected_api_id='';assert.throws(()=>validateSelection(input),/문자열의 배열/); });
