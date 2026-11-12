/* 전처리 JSON의 경로/타입/승인 상태를 유지한 데이터 조회·Baseline 편집. */
(function () {
  'use strict';
  if (!TAP) return;
  const data = () => TAP.preprocessing || { canonical_schema: {}, baselines: {}, parameter_kb: {}, response_outputs: {}, common_knowledge: [], warnings: [] };
  const code = value => `<code class="artifact-path">${esc(value == null ? '—' : String(value))}</code>`;
  const textValue = value => esc(value === undefined ? '—' : typeof value === 'string' ? value : JSON.stringify(value));
  const required = field => (field.requiredDeclared ?? field.required_declared) ? (field.required ? '필수' : '선택') : '미명시';
  const apis = dom => Object.entries(data().canonical_schema).filter(([sid]) => !dom || TAP.metadata.some(m => m.api_id === sid && m.domain === REAL_DOM[dom]));
  const apiDomain = sid => (TAP.metadata.find(m => m.api_id === sid) || {}).domain || 'unknown';
  const domainNames = { pd: '상품', od: '주문', ds: '물류', af: '재경', cs: '상담', hm: '전시', unknown: '미분류' };
  const documentId = (sid, canonical) => canonical.documentId || sid.split(':', 1)[0];
  const filteredApis = (dom, filter) => apis('domain' in filter ? null : dom).filter(([sid, a]) =>
    (!filter.domain || apiDomain(sid) === filter.domain) &&
    (!filter.document || documentId(sid, a) === filter.document) && (!filter.api || sid === filter.api));
  const apiName = (sid, canonical) => (TAP.metadata.find(m => m.api_id === sid) || {}).api_name || canonical.summary || canonical.operationId || canonical.apiId;
  const heading = (sid, canonical, extra = '') => `<h3 class="artifact-title">${esc(apiName(sid, canonical))} ${extra}</h3><p>${code(sid)}</p>`;
  const empty = '<p class="note">해당 JSON 산출물이 없습니다. 전처리 실행 후 갱신해 주세요.</p>';
  function fieldsTable(fields, valueKey) {
    return tbl(['필드 · 위치', 'parameter_path', 'xmlPath', '타입', '필수여부', valueKey === 'value' ? '값 · 출처' : 'example'], fields.map(p => `<tr>
      <td>${esc(p.name || '')}<br><span class="note">${esc(p.location || '')}</span></td><td>${code(p.parameter_path)}</td><td>${code(p.xmlPath)}</td>
      <td>${code(p.type)}</td><td>${required(p)}</td><td>${textValue(p[valueKey])}${valueKey === 'value' ? `<br><span class="note">${esc(p.value_source || '')}</span>` : ''}</td></tr>`), '필드가 없습니다.');
  }
  Object.assign(REAL_DOCS, {
    schema(dom, filter = {}) {
      const entries = filteredApis(dom, filter);
      return { count: `API ${entries.length}개 · 필드 ${entries.reduce((n, [, a]) => n + a.parameters.length, 0)}개`,
        body: entries.map(([sid, a]) => heading(sid, a) + `<p class="note">${esc(a.contentType || '본문 없음')} · 요청 본문 ${a.requestBodyRequired ? '필수' : '선택/미명시'}</p>` + fieldsTable(a.parameters, 'example')).join('') || empty };
    },
    baseline(dom, filter = {}) {
      const entries = filteredApis(dom, filter), count = entries.filter(([sid]) => data().baselines[sid]?.user_registered).length;
      return { count: `${count} / ${entries.length} 사용자 등록`, body: entries.map(([sid, a]) => {
        const baseline = data().baselines[sid];
        return heading(sid, a, `<span class="tag">${baseline?.user_registered ? '사용자 등록' : '예시 초안 · 미등록'}</span>`) +
          (baseline ? fieldsTable(baseline.parameters, 'value') : empty);
      }).join('') || empty };
    },
    pkb(dom, filter = {}) {
      const entries = filteredApis(dom, filter), fields = entries.reduce((n, [sid]) => n + (data().parameter_kb[sid]?.parameters.length || 0), 0);
      let body = entries.map(([sid, a]) => {
        const kb = data().parameter_kb[sid];
        if (!kb) return heading(sid, a) + empty;
        return heading(sid, a) + tbl(['필드 · 기본 의미', 'parameter_path', 'xmlPath', '타입', '필수여부', '승인된 API 지식'], kb.parameters.map(p => {
          const id = p.identity, schema = p.schema;
          const approved = kb.api_knowledge.filter(k => (k.targets || []).some(t => t.document_id === id.document_id && t.api_id === id.api_id && t.parameter_path === id.parameter_path));
          return `<tr><td>${esc(id.parameter_name)}<br><span class="note">${esc(p.knowledge.description || '')}</span></td>
            <td>${code(id.parameter_path)}</td><td>${code(schema.xml_path)}</td><td>${code(schema.type)}</td><td>${required(schema)}</td>
            <td>${approved.length ? approved.map(k => `<p><b>${esc(k.kind)}</b><br>${textValue(k.payload)}</p>`).join('') : '<span class="note">승인 보강 지식 없음 · Canonical 기본 지식</span>'}</td></tr>`;
        }), '기본 지식이 없습니다.');
      }).join('');
      const scopeNames = { pd: 'product', od: 'order', ds: 'logistics' };
      const domain = ('domain' in filter ? filter.domain : REAL_DOM[dom]) || (TAP.metadata.find(m => m.api_id === filter.api) || {}).domain;
      const scopeIds = [domain, scopeNames[domain], Object.keys(REAL_DOM).find(key => REAL_DOM[key] === domain)].filter(Boolean);
      const common = data().common_knowledge.filter(k => !domain || k.application_scope.type === 'GLOBAL' || scopeIds.includes(k.application_scope.domain_id));
      body += '<h3 class="artifact-title">승인된 공통 지식</h3>' + tbl(['종류', '적용 범위', '내용'], common.map(k => `<tr><td>${esc(k.kind)}</td><td>${textValue(k.application_scope)}</td><td>${textValue(k.payload)}</td></tr>`), '해당 범위의 승인된 공통 지식이 없습니다.');
      return { count: `기본 필드 ${fields}개`, body: body || empty };
    },
    resp(dom, filter = {}) {
      const entries = filteredApis(dom, filter);
      return { count: `활성 성공 필드 ${entries.reduce((n, [sid]) => n + (data().response_outputs[sid]?.outputs.length || 0), 0)}개`,
        body: entries.map(([sid, a]) => {
          const response = data().response_outputs[sid];
          if (!response) return heading(sid, a) + empty;
          return heading(sid, a) + `<p class="note">허용 성공 응답: ${response.responses.map(r => esc(`${r.response_key} · HTTP ${r.status_code} · ${r.content_type}`)).join(', ') || '없음'}</p>` +
            tbl(['출력', 'parameter_path', 'xmlPath / response_path', '타입', '필수여부', '성공 응답'], response.outputs.map(p => `<tr><td>${esc(p.name)}</td><td>${code(p.parameter_path)}</td><td>${code(p.xmlPath || p.response_path)}</td><td>${code(p.type)}</td><td>${required(p)}</td><td>${esc(p.response_key)}<br>${esc(p.content_type)}</td></tr>`), '사용 가능한 활성 성공응답 필드가 없습니다.') +
            `<details><summary>성공 응답 스키마</summary><pre class="code artifact-json">${esc(JSON.stringify(response.responses, null, 2))}</pre></details>`;
        }).join('') || empty };
    }
  });

  // 기존 이벤트에 연결된 저장 함수를 교체한다.
  el('blSave').removeEventListener('click', saveBaseline);
  const valuesOf = baseline => Object.fromEntries((baseline?.parameters || []).map(p => [p.parameter_path, p.value]));
  renderBaseline = function () {
    const entries = apis(S.dom), select = el('blEp'), current = select.value;
    el('blTitle').textContent = `Baseline Request · ${DOM_NAME(S.dom)}`;
    el('blForm').hidden = !entries.length;
    el('blEmpty').innerHTML = entries.length ? '' : empty;
    select.innerHTML = entries.map(([sid, a]) => `<option value="${esc(sid)}">${esc(apiName(sid, a))} · ${esc(a.apiId)}</option>`).join('');
    if (entries.some(([sid]) => sid === current)) select.value = current;
    const baseline = data().baselines[select.value];
    el('blStat').value = baseline?.user_registered ? '사용자 등록' : baseline ? '예시 초안 · 미등록' : '산출물 없음';
    if (document.activeElement !== el('blBody')) el('blBody').value = baseline ? JSON.stringify(valuesOf(baseline), null, 2) : '';
    const draft = el('blDraft'); draft.hidden = !baseline;
    draft.onclick = () => { el('blBody').value = JSON.stringify(baseline.example_values, null, 2); };
    el('blHist').textContent = `등록된 내역 (${entries.filter(([sid]) => data().baselines[sid]?.user_registered).length} / ${entries.length})`;
    el('blList').innerHTML = REAL_DOCS.baseline(S.dom).body;
  };
  saveBaseline = async function () {
    const sid = el('blEp').value;
    try {
      if (location.protocol === 'file:') throw new Error('로컬 서버로 열어야 사용자 등록값을 저장할 수 있습니다.');
      const values = JSON.parse(el('blBody').value);
      const saved = await api('/api/preprocessing/baseline', { selected_api_id: sid, values });
      rerenderAll();
      toast('blToast', `사용자 등록값 저장 · ${saved.file}`);
    } catch (error) { toast('blToast', '저장 실패: ' + error.message); }
  };
  el('blSave').addEventListener('click', saveBaseline);
  document.querySelector('label[for="blBody"]').textContent = '기본 요청값 · parameter_path별 JSON';
  el('blSave').textContent = '사용자 등록 · 검증';
  el('blDraft').textContent = 'example 초기값으로 채우기';

  let activeDoc = null;
  const artifactDocs = new Set(['schema', 'baseline', 'pkb', 'resp']);
  const filters = new Map();
  const previousOpenDoc = openDoc;
  openDoc = function (id, dom) {
    activeDoc = { id, dom };
    previousOpenDoc(id, dom);
    if (!artifactDocs.has(id)) return;
    const key = `${id}:${dom || 'all'}`;
    if (!filters.has(key)) filters.set(key, { domain: REAL_DOM[dom] || '', document: '', api: '' });
    const filter = filters.get(key), host = el('modalBody');
    // 탭 노드와 기존 클릭 이벤트를 보존하고 본문을 필터 가능한 영역으로 교체한다.
    const strip = host.querySelector('.docstrip');
    host.replaceChildren();
    if (strip) host.append(strip);
    host.insertAdjacentHTML('beforeend', `<div class="artifact-filters">
      <label for="artifactDomainFilter">도메인<select id="artifactDomainFilter" aria-label="도메인 필터"></select></label>
      <label for="artifactDocumentFilter">document<select id="artifactDocumentFilter" aria-label="document 필터"></select></label>
      <label for="artifactApiFilter">api_id<select id="artifactApiFilter" aria-label="api_id 필터"></select></label>
      </div><p id="artifactFilteredCount" class="note" role="status" aria-live="polite"></p><div id="artifactFilteredResults"></div>`);
    const domainSelect = el('artifactDomainFilter'), documentSelect = el('artifactDocumentFilter'), apiSelect = el('artifactApiFilter');
    const entries = apis(null);
    const domains = [...new Set(entries.map(([sid]) => apiDomain(sid)))].sort();
    if (filter.domain && !domains.includes(filter.domain)) filter.domain = '';
    domainSelect.innerHTML = '<option value="">도메인 전체</option>' + domains.map(value => `<option value="${esc(value)}">${esc(domainNames[value] || value)} (${esc(value)})</option>`).join('');
    domainSelect.value = filter.domain;
    function update() {
      const domainEntries = entries.filter(([sid]) => !filter.domain || apiDomain(sid) === filter.domain);
      const documents = [...new Set(domainEntries.map(([sid, a]) => documentId(sid, a)))].sort();
      if (filter.document && !documents.includes(filter.document)) filter.document = '';
      documentSelect.innerHTML = '<option value="">document 전체</option>' + documents.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('');
      documentSelect.value = filter.document;
      const candidates = domainEntries.filter(([sid, a]) => !filter.document || documentId(sid, a) === filter.document);
      if (filter.api && !candidates.some(([sid]) => sid === filter.api)) filter.api = '';
      apiSelect.innerHTML = '<option value="">api_id 전체</option>' + candidates.slice().sort(([, a], [, b]) => a.apiId.localeCompare(b.apiId)).map(([sid, a]) => `<option value="${esc(sid)}">${esc(a.apiId)} · ${esc(apiName(sid, a))}</option>`).join('');
      apiSelect.value = filter.api;
      const result = REAL_DOCS[id](dom, filter);
      el('artifactFilteredCount').textContent = result.count;
      el('artifactFilteredResults').innerHTML = result.body;
    }
    domainSelect.addEventListener('change', () => { filter.domain = domainSelect.value; update(); });
    documentSelect.addEventListener('change', () => { filter.document = documentSelect.value; update(); });
    apiSelect.addEventListener('change', () => { filter.api = apiSelect.value; update(); });
    update();
  };
  const refresh = el('refreshPreprocessing'), status = el('preprocessingStatus');
  function showStatus() {
    const counts = data().counts;
    status.textContent = counts ? `전처리 JSON · Canonical ${counts.canonical_schema} · KB ${counts.parameter_kb} · Baseline ${counts.baseline} · 응답 ${counts.response_outputs}${data().warnings.length ? ` · 확인 필요 ${data().warnings.length}건` : ''}` : '전처리 JSON을 갱신해 주세요.';
    status.title = (data().warnings || []).join('\n');
  }
  refresh.addEventListener('click', async () => {
    refresh.disabled = true;
    try {
      if (location.protocol === 'file:') throw new Error('갱신은 로컬 서버(tap.cli serve)로 열어 사용해 주세요.');
      await api('/api/preprocessing/refresh');
      showStatus(); rerenderAll();
      if (activeDoc && !el('modal').hidden) openDoc(activeDoc.id, activeDoc.dom);
    } catch (error) { status.textContent = '갱신 실패: ' + error.message; }
    finally { refresh.disabled = false; }
  });
  // 이후 파라미터 결정 서비스가 동일한 selected_api_id로 원본 정보를 조회한다.
  window.PreprocessingUI = { forSelectedApi: sid => ({ canonical_schema: data().canonical_schema[sid],
    parameter_kb: data().parameter_kb[sid], baseline: data().baselines[sid], response_outputs: data().response_outputs[sid] }) };
  showStatus();
  rerenderAll();
}());
