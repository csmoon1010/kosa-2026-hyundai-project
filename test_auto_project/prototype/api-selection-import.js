/* 의도 분석과 API 선택 결과를 불러오고, 사용자 승인 결과를 통합 파일로 저장한다. */
(function () {
  'use strict';

  function validateSelection(data) {
    const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    const text = value => typeof value === 'string' && value.trim().length > 0;
    const positive = value => Number.isInteger(value) && value > 0;
    const fail = message => { throw new Error(message); };
    if (!object(data)) fail('JSON 최상위는 객체여야 합니다.');
    if (!text(data.original_question)) fail('original_question에 원본 요청을 적어 주세요.');
    if (!text(data.status)) fail('status에 API 선택 결과의 상태를 적어 주세요.');
    if (!Array.isArray(data.api_selection_results) || !data.api_selection_results.length)
      fail('api_selection_results에 API 선택 결과를 1개 이상 넣어 주세요.');
    if (data.unresolved !== undefined && !Array.isArray(data.unresolved))
      fail('unresolved는 배열이어야 합니다. 미해결 항목이 없으면 []로 적어 주세요.');

    const keys = new Set(), domains = new Map();
    data.api_selection_results.forEach((row, index) => {
      const label = `api_selection_results[${index}]`;
      if (!object(row)) fail(`${label}는 객체여야 합니다.`);
      if (!positive(row.path_sequence) || !positive(row.step))
        fail(`${label}의 path_sequence와 step은 1 이상의 정수여야 합니다.`);
      const key = `${row.path_sequence}-${row.step}`;
      if (keys.has(key)) fail(`업무·단계 번호가 중복되었습니다: ${key}`);
      keys.add(key);
      ['domain', 'edge', 'selection_status', 'selection_reason'].forEach(field => {
        if (!text(row[field])) fail(`${label}.${field}를 적어 주세요.`);
      });
      if (domains.has(row.path_sequence) && domains.get(row.path_sequence) !== row.domain)
        fail(`업무 ${row.path_sequence}의 domain이 서로 다릅니다.`);
      domains.set(row.path_sequence, row.domain);
      if (!Array.isArray(row.api_candidates) || row.api_candidates.some(api => !text(api)))
        fail(`${label}.api_candidates는 API ID 문자열의 배열이어야 합니다.`);
      if (row.selected_api_id !== null && !text(row.selected_api_id))
        fail(`${label}.selected_api_id는 API ID 또는 null이어야 합니다.`);
      if (row.selected_api_id !== null && !row.api_candidates.includes(row.selected_api_id))
        fail(`${key}의 selected_api_id가 api_candidates에 없습니다.`);
      if (row.selected_api_id === null && ['선택', '승인', '선택 완료'].includes(row.selection_status))
        fail(`${key}는 API가 선택된 상태인데 selected_api_id가 null입니다.`);
    });
    (data.unresolved || []).forEach((issue, index) => {
      const label = `unresolved[${index}]`;
      if (!object(issue) || !positive(issue.path_sequence) || !domains.has(issue.path_sequence))
        fail(`${label}.path_sequence는 불러온 업무 번호여야 합니다.`);
      if (issue.step !== null && (!positive(issue.step) || !keys.has(`${issue.path_sequence}-${issue.step}`)))
        fail(`${label}.step은 해당 업무의 단계 번호 또는 null이어야 합니다.`);
      if (!text(issue.reason)) fail(`${label}.reason에 미해결 사유를 적어 주세요.`);
    });
    return data;
  }

  function validateIntent(data) {
    const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    const text = value => typeof value === 'string' && value.trim().length > 0;
    const positive = value => Number.isInteger(value) && value > 0;
    if (!object(data)) throw new Error('의도 분석 JSON 최상위는 객체여야 합니다.');
    if (!text(data.original_question)) throw new Error('original_question에 원본 요청을 적어 주세요.');
    if (!Array.isArray(data.tasks) || !data.tasks.length) throw new Error('tasks에 업무를 1개 이상 넣어 주세요.');
    const sequences = new Set();
    data.tasks.forEach((task, index) => {
      const label = `tasks[${index}]`;
      if (!object(task)) throw new Error(`${label}는 객체여야 합니다.`);
      ['domain', 'action'].forEach(key => {
        if (!text(task[key])) throw new Error(`${label}.${key}를 적어 주세요.`);
      });
      if (!text(task.conditions) && !(object(task.conditions) && Object.keys(task.conditions).length) && !(Array.isArray(task.conditions) && task.conditions.length && task.conditions.every(c => text(c) || (object(c) && Object.keys(c).length)))) throw new Error(`${label}.conditions를 적어 주세요.`);
      if (!positive(task.count) || !positive(task.sequence)) throw new Error(`${label}의 count와 sequence는 1 이상의 정수여야 합니다.`);
      if (sequences.has(task.sequence)) throw new Error(`업무 sequence가 중복되었습니다: ${task.sequence}`);
      sequences.add(task.sequence);
    });
    return data;
  }

  // 같은 검증 함수를 Node 테스트와 브라우저에서 사용한다.
  if (typeof module === 'object' && module.exports) module.exports = { validateSelection, validateIntent };
  if (typeof document === 'undefined') return;

  const DOMAIN = { PD: ['goods', '상품'], OD: ['order', '주문'], DS: ['logistics', '물류'] };
  const MAX_FILE_BYTES = 2 * 1024 * 1024;
  const input = el('apiSelectionFile'), example = el('loadSelectionExample');
  const intentInput = el('intentAnalysisFile'), intentExample = el('loadIntentExample');
  const message = el('apiSelectionImportStatus');
  let loading = false;

  function report(text, error = false) {
    message.textContent = text;
    message.dataset.error = String(error);
  }
  function setLoading(value) {
    loading = value;
    input.disabled = value;
    example.disabled = value;
    intentInput.disabled = value;
    intentExample.disabled = value;
  }
  function statusTag(status) {
    const color = ['선택', '승인', '선택 완료'].includes(status) ? 'st-ok' : 'st-rj';
    return `<span class="st ${color}">${esc(status)}</span>`;
  }
  function selectionCard(draft) {
    const data = draft.apiSelection, rows = data.api_selection_results;
    const groups = [...new Set(rows.map(row => row.path_sequence))].sort((a, b) => a - b);
    const pending = rows.filter(row => row.selection_status === '보류').length;
    const tentative = rows.filter(row => row.selection_status === '가선택').length;
    const intentMismatch = draft.intentAnalysis && draft.intentAnalysis.original_question !== data.original_question;
    const canApprove = Boolean(draft.intentAnalysis && !intentMismatch);
    let html = `<div class="card selection-result"><div class="card-hd"><h2>불러온 API 선택 결과</h2>${statusTag(data.status)}</div>
      <p class="selection-file">${esc(draft.apiSelectionFilename)}</p>
      <div class="selection-summary"><span class="tag">업무 ${groups.length}개</span><span class="tag">단계 ${rows.length}개</span>
        <span class="tag">API 지정 ${rows.filter(row => row.selected_api_id !== null).length}개</span>
        <span class="tag">보류 ${pending}개</span><span class="tag">가선택 ${tentative}개</span></div>
      <p class="note">파일에 기록된 후보·선택 상태를 그대로 표시합니다. 불러오기만으로 API 선택이 승인되거나 시나리오가 등록되지는 않습니다.</p></div>`;
    groups.forEach(sequence => {
      const steps = rows.filter(row => row.path_sequence === sequence).slice().sort((a, b) => a.step - b.step);
      const domain = steps[0].domain;
      html += `<div class="card selection-result"><div class="card-hd"><h2>업무 ${sequence} · ${esc((DOMAIN[domain] || [null, domain])[1])}</h2><span class="tag">${esc(domain)}</span></div>
        <div class="tbl-wrap"><table><thead><tr><th>단계 · 업무</th><th>선택된 API · 후보</th><th>선택 상태 · 이유</th><th>미해결 항목</th></tr></thead><tbody>
        ${steps.map((row, index) => {
          const rowIssues = (data.unresolved || []).filter(issue => issue.path_sequence === row.path_sequence &&
            (issue.step === row.step || (issue.step === null && index === 0)));
          return `<tr><td>${row.path_sequence}-${row.step}<br><b>${esc(row.edge)}</b></td>
          <td>${row.api_candidates.length > 1 || row.selected_api_id === null ? `<label class="selection-choice-label">선택 API
            <select class="selection-choice" data-path="${row.path_sequence}" data-step="${row.step}" aria-label="업무 ${row.path_sequence} 단계 ${row.step} API 선택">
              <option value="">미선택</option>${row.api_candidates.map(api => `<option value="${esc(api)}"${row.selected_api_id === api ? ' selected' : ''}>${esc(api)}</option>`).join('')}
            </select></label>` : `<code class="selection-api">${esc(row.selected_api_id)}</code>`}
            <details><summary>API 후보 ${row.api_candidates.length}개</summary><ul class="selection-candidates">${row.api_candidates.map(api => `<li><code>${esc(api)}</code></li>`).join('')}</ul></details></td>
          <td>${statusTag(row.selection_status)}<p class="selection-reason">${esc(row.selection_reason)}</p></td>
          <td>${rowIssues.length ? `<ul class="selection-row-issues">${rowIssues.map(issue => `<li><b>${issue.step === null ? '업무 전체' : `단계 ${issue.step}`}</b><br>${esc(issue.reason)}</li>`).join('')}</ul>` : '<span class="note">해당 없음</span>'}</td></tr>`;
        }).join('')}
        </tbody></table></div></div>`;
    });
    html += `<div class="card selection-result">
      <details><summary>불러온 JSON 원본 보기</summary><pre class="code selection-raw">${esc(JSON.stringify(data, null, 2))}</pre></details>
      <div class="btn-row"><button type="button" class="btn btn-primary" id="approveSelectionFile"${canApprove ? '' : ' disabled'}>승인</button></div>
      <p class="note">${!draft.intentAnalysis ? '통합 승인 파일을 만들려면 의도 분석 파일도 불러와 주세요.' : intentMismatch ? '두 파일의 original_question이 일치하지 않아 승인할 수 없습니다.' : '의도 업무와 API 선택 결과를 한 파일로 저장합니다. 원본 파일은 변경하지 않습니다.'}</p></div>`;
    if (draft.approvedJson) html += `<div class="card selection-result approval-json"><div class="card-hd"><h2>생성된 통합 승인 JSON</h2><span class="tag">${esc(draft.approvedJson.approval_status)}</span></div>
      <p class="selection-file">${esc(draft.approvedFile || '저장 대기 · prototype/approved')}</p><details open><summary>JSON 미리보기</summary><pre class="code selection-raw">${esc(JSON.stringify(draft.approvedJson, null, 2))}</pre></details></div>`;
    return html;
  }

  function intentCard(draft) {
    const data = draft.intentAnalysis;
    const mismatch = draft.apiSelection && data.original_question !== draft.apiSelection.original_question;
    return `<div class="card selection-result"><div class="card-hd"><h2>불러온 의도 분석 결과</h2><span class="tag">업무 ${data.tasks.length}개</span></div>
      <p class="selection-file">${esc(draft.intentAnalysisFilename || '')}</p>
      <p class="note">원본 질문: ${esc(data.original_question)}</p>
      ${mismatch ? '<p class="selection-import-status" data-error="true">의도 분석과 API 선택 파일의 original_question이 서로 다릅니다.</p>' : ''}
      <div class="tbl-wrap"><table><thead><tr><th>순서 · 도메인</th><th>업무</th><th>조건 · 건수</th></tr></thead><tbody>
      ${data.tasks.slice().sort((a, b) => a.sequence - b.sequence).map(task => `<tr><td>${task.sequence} · ${esc(task.domain)}</td><td><b>${esc(task.action)}</b></td><td>${esc(typeof task.conditions==='string'?task.conditions:JSON.stringify(task.conditions))}<br><span class="note">${task.count}건</span></td></tr>`).join('')}
      </tbody></table></div></div>`;
  }

  const previousRenderRegList = renderRegList;
  renderRegList = function () {
    previousRenderRegList();
    if (S.regDraft && S.regDraft.apiSelection) {
      const badge = el('regTable').querySelector('tr.draft .st');
      if (badge) badge.textContent = 'API 선택 입력';
    }
  };
  const previousRenderReg = renderReg;
  renderReg = function () {
    const draft = S.regDraft, imported = Boolean(draft && draft.apiSelection);
    if (imported) {
      renderRegList();
      el('editTitle').textContent = 'API 선택 결과 · 시나리오 등록 준비';
      el('scName').value = draft.name;
      el('scUtt').value = draft.utterance;
      renderDomChips(draft);
      el('scDoms').querySelectorAll('button').forEach(button => { button.disabled = true; });
      el('extractOut').innerHTML = (draft.intentAnalysis ? intentCard(draft) : '') + selectionCard(draft);
      wireApprovalControls(draft);
      el('confirmOut').innerHTML = `<div class="card"><div class="card-hd"><h2 class="sm">파라미터 매핑을 위한 입력</h2></div>
        <p class="note">불러온 API 선택 결과는 Scenario IR 생성 전의 입력입니다. 선택된 API와 보류·가선택·미해결 항목을 검토하세요.</p>
        <p class="note">다른 요청을 새로 생성하려면 상단의 <b>＋ 새 시나리오 등록</b>을 누르세요.</p></div>`;
    } else {
      previousRenderReg();
      if (draft && draft.intentAnalysis) el('extractOut').innerHTML = intentCard(draft) + el('extractOut').innerHTML;
    }
    el('scUtt').readOnly = imported;
    el('extractBtn').hidden = imported;
    el('realSamples').hidden = imported;
    if (!imported && !loading) report('');
  };

  function importSelection(data, filename) {
    validateSelection(data); // 형식이 잘못되면 기존 초안을 유지한다.
    setView('reg');
    const domains = [...new Set(data.api_selection_results.map(row => (DOMAIN[row.domain] || [])[0]).filter(Boolean))];
    const previous = S.regDraft || {};
    S.regNew = true;
    S.regSelected = null;
    S.regDraft = { name: filename.replace(/\.json$/i, ''), utterance: data.original_question,
      domains, apiSelection: data, apiSelectionFilename: filename,
      intentAnalysis: previous.intentAnalysis, intentAnalysisFilename: previous.intentAnalysisFilename };
    renderReg();
    report(`${filename} 불러옴`);
    focusEditor();
  }

  function importIntent(data, filename) {
    validateIntent(data);
    setView('reg');
    const previous = S.regDraft || {};
    S.regNew = true;
    S.regSelected = null;
    S.regDraft = { name: previous.apiSelection ? previous.name : filename.replace(/\.json$/i, ''),
      utterance: data.original_question, domains: previous.domains || [],
      apiSelection: previous.apiSelection, apiSelectionFilename: previous.apiSelectionFilename,
      intentAnalysis: data, intentAnalysisFilename: filename };
    renderReg();
    report(`${filename} 불러옴${S.regDraft.apiSelection && S.regDraft.apiSelection.original_question !== data.original_question ? ' · 두 파일의 원본 질문이 다릅니다' : ''}`,
      Boolean(S.regDraft.apiSelection && S.regDraft.apiSelection.original_question !== data.original_question));
    focusEditor();
  }

  function wireApprovalControls(draft) {
    el('extractOut').querySelectorAll('.selection-choice').forEach(select => {
      select.addEventListener('change', () => {
        const row = draft.apiSelection.api_selection_results.find(item =>
          item.path_sequence === Number(select.dataset.path) && item.step === Number(select.dataset.step));
        if (!row) return;
        row.selected_api_id = select.value || null;
        delete draft.approvedJson;
        delete draft.approvedFilename;
        renderReg();
      });
    });
    const button = el('approveSelectionFile');
    if (button) button.addEventListener('click', () => createApprovalJson(draft));
  }

  async function createApprovalJson(draft) {
    if (!draft.intentAnalysis || draft.intentAnalysis.original_question !== draft.apiSelection.original_question) return;
    const apiRows = JSON.parse(JSON.stringify(draft.apiSelection.api_selection_results));
    let approvedCount = 0;
    apiRows.forEach(row => {
      const approved = Boolean(row.selected_api_id && row.api_candidates.includes(row.selected_api_id));
      row.approval_status = approved ? 'approved' : 'unapproved';
      if (approved) approvedCount += 1;
      delete row.selection_status;
    });
    const allApproved = approvedCount === apiRows.length;
    const combined = {
      original_question: draft.apiSelection.original_question,
      approval_status: allApproved ? 'approved' : 'unapproved',
      intent_tasks: JSON.parse(JSON.stringify(draft.intentAnalysis.tasks)),
      api_selection_results: apiRows,
      unresolved: JSON.parse(JSON.stringify(draft.apiSelection.unresolved || [])),
      source_files: {
        intent_analysis: draft.intentAnalysisFilename,
        api_selection: draft.apiSelectionFilename
      }
    };
    const sourceBase = (draft.apiSelectionFilename || 'api-selection.json').replace(/^api-selection-?/i, '').replace(/\.json$/i, '') || 'result';
    const filename = `api-selection-approved-${sourceBase}.json`;
    draft.approvedJson = combined;
    draft.approvedFilename = filename;
    draft.approvedFile = null;
    renderReg();
    if (location.protocol === 'file:') {
      report(`JSON 생성 완료 · 로컬 서버로 열어야 prototype/approved에 저장할 수 있습니다.`, true);
      return;
    }
    try {
      const saved = await api('/api/approved-selections', { filename, approved_json: combined });
      draft.approvedFile = saved.file;
      draft.approvedFilename = saved.filename;
      renderReg();
      if (allApproved && window.ScenarioIRDraft) window.ScenarioIRDraft.generate(saved.filename);
      report(`승인 JSON 저장 완료 · ${saved.file} · ${approvedCount}/${apiRows.length}개 API 승인${allApproved ? '' : ' · 전체 상태는 unapproved'}`, !allApproved);
    } catch (error) {
      report(`JSON은 생성됐지만 prototype/approved 저장에 실패했습니다: ${error.message}`, true);
    }
  }

  input.addEventListener('change', async () => {
    const file = input.files[0];
    if (!file) return;
    setLoading(true);
    try {
      if (file.size > MAX_FILE_BYTES) throw new Error('2MB 이하의 JSON 파일을 선택해 주세요.');
      const text = (await file.text()).replace(/^\uFEFF/, '');
      importSelection(JSON.parse(text), file.name);
    } catch (error) {
      report('파일을 불러오지 못했습니다: ' + (error instanceof SyntaxError ? 'JSON 문법을 확인해 주세요.' : error.message), true);
    } finally {
      input.value = '';
      setLoading(false);
    }
  });
  intentInput.addEventListener('change', async () => {
    const file = intentInput.files[0];
    if (!file) return;
    setLoading(true);
    try {
      if (file.size > MAX_FILE_BYTES) throw new Error('2MB 이하의 JSON 파일을 선택해 주세요.');
      const text = (await file.text()).replace(/^\uFEFF/, '');
      importIntent(JSON.parse(text), file.name);
    } catch (error) {
      report('파일을 불러오지 못했습니다: ' + (error instanceof SyntaxError ? 'JSON 문법을 확인해 주세요.' : error.message), true);
    } finally {
      intentInput.value = '';
      setLoading(false);
    }
  });
  example.addEventListener('click', async () => {
    setLoading(true);
    try {
      if (location.protocol === 'file:') throw new Error('예시 버튼은 로컬 서버로 열었을 때 사용할 수 있습니다. 파일 선택에서 prototype/examples의 JSON을 직접 선택할 수도 있습니다.');
      const response = await fetch('examples/api-selection-order-shipment.json', { cache: 'no-store' });
      if (!response.ok) throw new Error(`예시 파일을 찾지 못했습니다 (HTTP ${response.status}).`);
      importSelection(await response.json(), 'api-selection-order-shipment.json');
    } catch (error) {
      report('예시를 불러오지 못했습니다: ' + error.message, true);
    } finally {
      setLoading(false);
    }
  });
  intentExample.addEventListener('click', async () => {
    setLoading(true);
    try {
      if (location.protocol === 'file:') throw new Error('예시 버튼은 로컬 서버로 열었을 때 사용할 수 있습니다. 파일 선택에서 prototype/examples의 JSON을 직접 선택할 수도 있습니다.');
      const response = await fetch('examples/intent-analysis-order-shipment.json', { cache: 'no-store' });
      if (!response.ok) throw new Error(`예시 파일을 찾지 못했습니다 (HTTP ${response.status}).`);
      importIntent(await response.json(), 'intent-analysis-order-shipment.json');
    } catch (error) {
      report('예시를 불러오지 못했습니다: ' + error.message, true);
    } finally {
      setLoading(false);
    }
  });
  window.ApiSelectionImport = { validateSelection, validateIntent, importSelection, importIntent };
}());
