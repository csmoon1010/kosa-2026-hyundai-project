/* 시나리오 등록 — 최종 화면 (2026-11-12, P1 · P2 · P3)
   자연어 요청 → ① 요청 이해 → ② 경로 찾기 → ③ API 고르기 → 시나리오 생성(혜정 IR) → 승인 · 등록 → (P4) 실행 메뉴
   중간 산출물(후보 · 점수 · 트레이스 · JSON · 생성 로그)은 보여 주지 않는다 — 그건 '시나리오 등록(확인용)' 화면.
   서버
     POST /api/select (Accept: application/x-ndjson)   단계 시작마다 {"event":"stage"}, 마지막 줄이 결과
     POST /api/review-draft {selection_hash}           승인 전 검토용 초안 (data/ir_inputs/review-*.json)
     POST /api/scenario-ir-drafts (ndjson)             혜정 IR — scenario_steps → step_preview(단계마다) → generation_complete
     POST /api/register                                 승인 + 등록 (data/registered/) · GET /api/registered/<id> · POST /api/registered/delete
   확인할 것 = 사람이 확인하지 않은 API 선택(가선택 · LLM) — 단계마다 체크해야 등록된다.
   메모 = ①② 미해결 · IR 이 남긴 질문 — 접어서 보여 주기만 (2026-11-12 결정)
   offline-ui.html 의 전역 도우미(el · esc · RDOM_NAME · DOM_NAME · shortApi · SERVER · S · TAP)를 쓴다. */
(function(){
  'use strict';
  const STAGES = [['intent', '요청 이해'], ['paths', '경로 찾기'], ['apis', 'API 고르기'], ['ir', '시나리오 생성']];
  const LIVE = ['intent', 'paths', 'apis'];
  const fresh = () => ({ busy: false, stages: {}, result: null, handoff: null, irSteps: {}, irTotal: 0, ir: null, irFile: null,
    irError: null, checked: {}, registered: null, regError: null, regBusy: false });
  let state = fresh();
  let viewing = null;                             // 등록된 시나리오를 보는 중이면 그 기록 (읽기 전용)
  const regs = (typeof TAP !== 'undefined' && TAP && (TAP.registered = TAP.registered || [])) || [];   // 실행 메뉴(scenario-run.js)와 같은 목록

  const $ = id => document.getElementById(id);
  const domName = d => RDOM_NAME[String(d || '').toLowerCase()] || d;
  const apiCode = id => shortApi(id).split('/').pop().replace(/\.do$/, '');
  const clean = msg => String(msg || '').replace(/^\w+(Error|Exceeded|Stopped)?:\s*/, '').replace(/\s*\[[A-Z_]+\]\s*$/, '');
  const keyOf = r => `${r.path_sequence}-${r.step}`;
  const labelOf = (apiId, field) => {
    const op = TAP && (TAP.ops || []).find(o => o.id === apiId);
    const f = op && (op.req || []).find(x => x[0] === field);
    return f && f[1] ? f[1] : '';
  };
  const store = { get(k){ try { return localStorage.getItem(k) || ''; } catch (e){ return ''; } },
                  set(k, v){ try { localStorage.setItem(k, v); } catch (e){ /* 저장 못 해도 동작 */ } } };
  async function post(url, body){
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `서버 오류 (${r.status})`);
    return j;
  }

  /* ── NDJSON 읽기 — 한 줄씩 onEvent. 진행 줄이 없는 서버면 JSON 하나를 돌려준다 ── */
  async function readLines(res, onEvent){
    if (!(res.headers.get('Content-Type') || '').includes('ndjson')) return res.json();
    const onLine = line => { if (line.trim()) onEvent(JSON.parse(line)); };
    if (res.body && res.body.getReader){
      const reader = res.body.getReader(), dec = new TextDecoder();
      let buf = '';
      for (;;){
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n'); buf = lines.pop();
        lines.forEach(onLine);
      }
      onLine(buf);
    } else (await res.text()).split('\n').forEach(onLine);
    return null;
  }

  /* ── 등록된 시나리오 목록 ── */
  const stale = s => s.catalog_version != null && TAP && TAP.build && TAP.build.catalog_version != null && s.catalog_version !== TAP.build.catalog_version;
  function renderList(){
    const box = $('finList');
    if (!box) return;
    $('finCnt').textContent = `(${regs.length})`;
    box.innerHTML = regs.length ? `<thead><tr><th>순번</th><th>시나리오명</th><th>자연어 요청</th><th>도메인</th><th>단계</th><th>등록</th><th>상태</th><th></th></tr></thead><tbody>`
      + regs.map((s, i) => `<tr class="row ${viewing && viewing.id === s.id ? 'cur' : ''}" data-reg="${esc(s.id)}" tabindex="0" aria-label="${esc(s.name)} 보기">
        <td class="v">${i + 1}</td><td style="font-size:13px;font-weight:500">${esc(s.name)}</td><td class="desc" title="${esc(s.utterance)}">${esc(s.utterance)}</td>
        <td>${(s.domains || []).map(d => `<span class="tag">${esc(domName(d))}</span>`).join('')}</td>
        <td class="v">${s.steps}${s.irreversible ? ` <span class="fin-badge warn-b" title="되돌릴 수 없는 단계">R2 ${s.irreversible}</span>` : ''}</td>
        <td class="v">${esc(s.registered_at || '')}<br><span style="color:var(--muted)">${esc(s.approver || '')}</span></td>
        <td>${stale(s) ? '<span class="st st-rb">재승인 필요</span>' : '<span class="st st-ok">등록</span>'}</td>
        <td class="acts"><button class="xlink" type="button" data-regdel="${esc(s.id)}">삭제</button></td></tr>`).join('') + '</tbody>'
      : '<tbody><tr><td class="nodata">등록된 시나리오가 없습니다. 아래에 자연어 요청을 입력하고 분석하세요.</td></tr></tbody>';
    box.querySelectorAll('[data-reg]').forEach(tr => {
      const open = () => openSaved(tr.dataset.reg);
      tr.addEventListener('click', e => { if (!e.target.closest('.acts')) open(); });
      tr.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target === tr){ e.preventDefault(); open(); } });
    });
    box.querySelectorAll('[data-regdel]').forEach(b => b.addEventListener('click', async () => {
      if (!b.dataset.armed){ b.dataset.armed = '1'; b.textContent = '삭제 확인'; b.style.color = 'var(--danger)';
        setTimeout(() => { if (b.isConnected){ delete b.dataset.armed; b.textContent = '삭제'; b.style.color = ''; } }, 3000); return; }
      const id = b.dataset.regdel;
      try { await post('/api/registered/delete', { id }); }
      catch (e){ say('삭제하지 못했어요: ' + e.message); return; }
      const i = regs.findIndex(x => x.id === id); if (i >= 0) regs.splice(i, 1);
      if (viewing && viewing.id === id) viewing = null;
      if (state.registered && state.registered.id === id) state.registered = null;   // 방금 등록한 것을 지웠으면 다시 등록할 수 있게
      renderList(); show();
    }));
  }
  async function openSaved(id){
    try {
      const r = await fetch('/api/registered/' + encodeURIComponent(id), { cache: 'no-store' });
      const rec = await r.json();
      if (!r.ok) throw new Error(rec.error || r.status);
      viewing = rec;
    } catch (e){ say('불러오지 못했어요: ' + e.message); return; }
    renderList(); show();
    $('finOut').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  /* 등록 기록 → 미리보기가 읽는 모양 */
  function savedView(rec){
    const irSteps = {};
    ((rec.ir && rec.ir.tasks) || []).forEach(t => (t.steps || []).forEach(s => { irSteps[s.step_id] = s; }));
    return { stages: {}, result: { tasks: rec.tasks, apis: rec.selection, gate: rec.gate, paths: rec.paths },
             handoff: { steps: rec.step_map || [] }, irSteps, ir: rec.ir, irError: null, saved: rec };
  }

  /* ── 진행 표시 ── */
  function renderSteps(){
    const box = $('finSteps');
    if (!box) return;
    $('finProgress').hidden = !!viewing || !state.result && !state.busy;
    box.innerHTML = STAGES.map(([k, label], i) => {
      const s = state.stages[k] || 'wait';
      const mark = s === 'now' ? '<span class="spinner" aria-hidden="true"></span>'
        : s === 'done' ? '✓' : s === 'fail' ? '!' : String(i + 1);
      const sayIt = { now: '진행 중', done: '완료', fail: '멈춤', wait: '대기', off: '' }[s];
      const count = k === 'ir' && s === 'now' && state.irTotal ? ` <span class="fin-cnt">${Object.keys(state.irSteps).length}/${state.irTotal}</span>` : '';
      return `<li data-s="${s}"><span class="fin-dot">${mark}</span><span class="fin-lb">${esc(label)}${count}</span>`
        + (sayIt ? `<span class="sr-only"> — ${sayIt}</span>` : '') + '</li>';
    }).join('');
  }
  function setStage(k){
    const at = LIVE.indexOf(k);
    LIVE.forEach((x, i) => { state.stages[x] = i < at ? 'done' : i === at ? 'now' : 'wait'; });
    renderSteps();
  }

  /* ── 미리보기 (v = 지금 분석한 것 state 또는 등록 기록 savedView) ── */
  function apiName(row){
    const c = (row.api_candidates || []).find(x => row.selected && x.api_id === row.selected.api_id);
    return c && c.name ? c.name : '';
  }
  const apiLabel = row => row.selected ? (apiName(row) || apiCode(row.selected.api_id)) : '-';
  function irStepOf(v, row){
    const m = v.handoff && (v.handoff.steps || []).find(s => s.source_step === keyOf(row));
    return m ? v.irSteps[m.step_id] : null;
  }
  /* 단계 입력값 — 표: 필드명 · 필드설명 · 입력값 (2026-11-12). 필드설명은 명세의 한글 이름(없으면 빈칸)
     bindings: IR 모양({binding_id, from:{from_step_id, output_name}}) · 실행 이력 모양({binding_id, from_step_id, output_name}) 둘 다 받는다 */
  function paramTable(apiId, inputs, bindings){
    const binds = Object.fromEntries((bindings || []).map(b => [b.binding_id, b.from || b]));
    const rows = (inputs || []).map(x => {
      let val;
      if (x.source === 'fixed') val = `<td class="fin-pv">${esc(x.value ?? '')}</td>`;
      else if (x.source === 'bind'){
        const f = binds[x.ref] || {}, n = String(f.from_step_id || '').split('-').pop() || '?';
        val = `<td class="fin-pv bind">단계 ${esc(n)}의 <span class="mono">${esc(f.output_name || '')}</span></td>`;
      } else val = '<td class="fin-pv open">정해지지 않음</td>';
      return `<tr><td class="mono">${esc(x.field)}</td><td>${esc(labelOf(apiId, x.field))}</td>${val}</tr>`;
    });
    return rows.length ? `<div class="fin-pt-wrap"><table class="fin-pt"><thead><tr><th>필드명</th><th>필드설명</th><th>입력값</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>`
      : '<div class="fin-wait">바꿀 입력 없음 — 기본값 그대로</div>';
  }
  function inputsHtml(v, row, ir){
    if (!ir) return v.stages.ir === 'now' ? '<div class="fin-wait">입력값 만드는 중…</div>' : '';
    return paramTable(row.selected.api_id, ir.inputs, ir.bindings);
  }
  function stepRow(v, row, n){
    const g = (v.result.gate.steps || []).find(s => s.key === keyOf(row)) || {};
    const badges = [];
    if (g.tier === 'R2') badges.push('<span class="fin-badge warn-b">되돌릴 수 없음</span>');
    if (g.requirement === '단계 승인') badges.push('<span class="fin-badge chk-b">확인 필요</span>');   // 가선택 · LLM 이 고른 API
    const move = row.kind === '상태변경' && row.from && row.to ? `<span class="fin-move">${esc(row.from)} → ${esc(row.to)}</span>` : '';
    const api = row.selected ? `<span class="fin-api">${esc(apiLabel(row))}`
      + (apiName(row) ? ` <span class="mono">${esc(apiCode(row.selected.api_id))}</span>` : '') + '</span>' : '';
    return `<li><span class="fin-kind"><b>${n}</b> ${esc(row.kind)}</span><div class="fin-sb"><div class="fin-edge">${esc(row.edge)} ${move}</div>${api}`
      + `${inputsHtml(v, row, irStepOf(v, row))}</div><div class="fin-bs">${badges.join('')}</div></li>`;
  }
  /* 단계 번호 = 업무 안에서 몇 번째 (IR 단계 번호와 같다) */
  function ordinal(j, key){
    const rows = j.apis.api_selection_results || [], r = rows.find(x => keyOf(x) === key);
    if (!r) return { r: null, label: key };
    const n = rows.filter(x => x.path_sequence === r.path_sequence).sort((a, b) => a.step - b.step).indexOf(r) + 1;
    return { r, label: `업무 ${r.path_sequence} · 단계 ${n}` };
  }
  function toConfirm(j){                          // 확인할 것 — 가선택 · LLM 이 고른 API
    return (j.gate.need_steps || []).map(k => {
      const { r, label } = ordinal(j, k);
      const why = (j.apis.unresolved || []).filter(u => keyOf(u) === k).map(u => clean(u.reason));
      return { key: k, label, head: `${r ? r.edge : k} — ${r ? apiLabel(r) : '-'}`, why };
    });
  }
  function memos(v){                              // 메모 — ①② 미해결 · IR 이 남긴 질문
    const j = v.result, out = [], seen = new Set();
    [...(j.tasks.unresolved || []), ...((j.paths && j.paths.unresolved) || [])].forEach(u => {
      const t = clean(typeof u === 'string' ? u : (u.reason || ''));
      if (t && !seen.has(t)){ seen.add(t); out.push({ text: t, where: '' }); }
    });
    ((v.ir && v.ir.unresolved) || []).filter(u => u.status === 'open').forEach(u => {
      out.push({ text: clean(u.reason), where: (u.step_ids || []).map(s => `업무 ${s.split('-')[0]} · 단계 ${s.split('-')[1]}`).join(', ') });
    });
    return out;
  }
  function approveHtml(v){
    const j = v.result, list = toConfirm(j), rec = v.saved;
    const r2 = (j.gate.steps || []).some(s => s.tier === 'R2');
    const items = list.map(c => {
      const done = rec ? (rec.approval.steps || []).includes(c.key) : !!state.checked[c.key];
      return `<li><label><input type="checkbox" data-fin-chk="${esc(c.key)}" ${done ? 'checked' : ''} ${rec ? 'disabled' : ''}>`
        + ` <b>${esc(c.label)}</b> ${esc(c.head)} — API 가 맞는지 확인했어요</label>`
        + (c.why.length ? `<span class="fin-why">${c.why.map(esc).join(' · ')}</span>` : '') + '</li>';
    }).join('');
    const confirmBox = list.length ? `<h3>확인할 것 <span class="cnt">${list.length}</span></h3><ul class="fin-chk">${items}</ul>` : '';
    if (rec) return `<div class="fin-approve">${confirmBox}<p class="fin-done">✓ 등록됨 — 승인 ${esc(rec.approval.approver)} · ${esc(rec.registered_at)}</p></div>`;
    if (state.registered) return `<div class="fin-approve">${confirmBox}<p class="fin-done">✓ 등록했어요 — ${esc(state.registered.name)}</p></div>`;
    const ready = !!state.ir && !state.busy && list.every(c => state.checked[c.key]);
    const why = !state.ir ? (state.irError ? '시나리오를 만든 뒤 등록할 수 있어요.' : '시나리오를 만드는 중이에요.')
      : !list.every(c => state.checked[c.key]) ? '확인할 것을 모두 체크하면 등록할 수 있어요.' : '';
    return `<div class="fin-approve">${confirmBox}
      <div class="fin-who"><label for="finWho">승인자</label><input type="text" id="finWho" value="${esc(store.get('tdg.approver'))}" placeholder="이름"></div>
      ${r2 ? '<p class="fin-why">되돌릴 수 없는 단계는 실행할 때마다 다시 확인해요.</p>' : ''}
      <div class="btn-row"><button class="btn btn-primary" id="finApprove" type="button" ${ready && !state.regBusy ? '' : 'disabled'}>${state.regBusy ? '등록 중…' : '승인하고 등록'}</button></div>
      <p class="fin-why" id="finHint">${why}</p>${state.regError ? `<p class="fin-err">${esc(state.regError)}</p>` : ''}</div>`;
  }
  function preview(v){
    const j = v.result, tasks = j.tasks.tasks || [], rows = j.apis.api_selection_results || [], g = j.gate;
    const list = toConfirm(j), memo = memos(v);
    const taskHtml = tasks.map(t => {
      const mine = rows.filter(r => r.path_sequence === t.sequence).sort((a, b) => a.step - b.step);
      // 업무는 짧은 이름(배송완료) 대신 설명 문장으로 (2026-11-12)
      return `<section class="fin-task"><div class="fin-th"><b>업무 ${t.sequence}</b> <span class="fin-desc">${esc(t.conditions || t.action)}</span>`
        + `<span class="tag">${esc(domName(t.domain))}</span><span class="tag">${esc(t.origin)}</span>${t.count ? `<span class="tag">${t.count}건</span>` : ''}</div>`
        + (mine.length ? `<ol class="fin-list">${mine.map((r, i) => stepRow(v, r, i + 1)).join('')}</ol>` : '<p class="nodata">이 업무에 실행할 단계가 없어요.</p>')
        + '</section>';
    }).join('');
    const memoHtml = memo.length ? `<details class="fin-memo"><summary>메모 ${memo.length}개</summary><ul>${memo.map(m =>
      `<li>${esc(m.text)}${m.where ? `<span class="fin-why">${esc(m.where)}</span>` : ''}</li>`).join('')}</ul></details>` : '';
    const irFail = v.irError ? `<div class="fin-irfail"><b>시나리오를 만들지 못했어요</b><span>${esc(clean(v.irError))}</span>`
      + '<button class="btn btn-ghost btn-sm" type="button" data-fin-ir-retry>다시 만들기</button></div>' : '';
    const n = rows.length, r2 = (g.steps || []).filter(s => s.tier === 'R2').length;
    const title = v.saved ? esc(v.saved.name) : '시나리오 미리보기';
    return `<div class="card fade"><div class="card-hd hd-row"><h2 class="sm">${title}</h2>`
      + `<span class="fin-sum">단계 ${n}개${r2 ? ` · 되돌릴 수 없는 단계 ${r2}개` : ''}${list.length ? ` · 확인할 것 ${list.length}개` : ''}</span></div>`
      + (v.saved ? `<p class="fin-cond">${esc(v.saved.utterance)}</p>` : '')
      + irFail + taskHtml + memoHtml + approveHtml(v)
      + (v.saved ? '<div class="btn-row"><button class="btn btn-ghost btn-sm" type="button" data-fin-close>닫기</button></div>' : '') + '</div>';
  }
  function stopped(title, items, retry){
    return `<div class="card fade fin-stop"><div class="card-hd"><h2 class="sm">${esc(title)}</h2></div>`
      + (items.length ? `<ul>${items.map(x => `<li>${esc(clean(x))}</li>`).join('')}</ul>` : '')
      + (retry ? '<div class="btn-row"><button class="btn btn-ghost btn-sm" type="button" data-fin-retry>다시 분석</button></div>' : '') + '</div>';
  }
  const canBuild = j => j && !j.error && !['차단', '실행할 것 없음'].includes(j.gate.status);
  function renderResult(){
    const out = $('finOut');
    if (!out) return;
    const v = viewing ? savedView(viewing) : state, j = v.result;
    if (!j){ out.innerHTML = ''; return; }
    let html;
    if (j.error) html = stopped('분석하지 못했어요', [j.error], true);
    else if (j.gate.status === '차단') html = stopped('이 요청은 등록할 수 없어요', j.gate.blocked || [], false);
    else if (j.gate.status === '실행할 것 없음') html = stopped('실행할 단계가 없어요', (j.tasks.unresolved || []).map(u => u.reason || u), false);
    else html = preview(v);
    out.innerHTML = html;
    const on = (sel, f) => { const b = out.querySelector(sel); if (b) b.addEventListener('click', f); };
    on('[data-fin-retry]', analyze);
    on('[data-fin-ir-retry]', () => run(buildIr));
    on('[data-fin-close]', () => { viewing = null; renderList(); show(); });
    on('#finApprove', register);
    out.querySelectorAll('[data-fin-chk]').forEach(c => c.addEventListener('change', () => {
      state.checked[c.dataset.finChk] = c.checked; refreshApprove();      // 다시 그리지 않는다 — 키보드 위치 유지
    }));
    const who = $('finWho');
    if (who) who.addEventListener('input', () => store.set('tdg.approver', who.value.trim()));
  }
  function refreshApprove(){
    const b = $('finApprove'), hint = $('finHint');
    if (!b) return;
    const list = toConfirm(state.result), all = list.every(c => state.checked[c.key]);
    b.disabled = !(state.ir && !state.busy && !state.regBusy && all);
    if (hint) hint.textContent = !state.ir ? hint.textContent : all ? '' : '확인할 것을 모두 체크하면 등록할 수 있어요.';
  }

  /* ── ①②③ ── */
  async function select(utt){
    state.stages = { ir: 'wait' };
    setStage('intent'); renderResult();
    let result = null;
    try {
      const res = await fetch('/api/select', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/x-ndjson' },
        body: JSON.stringify({ utterance: utt, stop_retry: true }) });
      const plain = await readLines(res, ev => {
        if (ev.event === 'stage') setStage(ev.stage);
        else if (ev.event === 'done' || ev.event === 'error') result = ev.result;
      });
      result = result || plain;
      if (!res.ok && !result) result = { error: `서버 오류 (${res.status})` };
    } catch (e){
      result = { error: '서버에 연결하지 못했어요: ' + e.message };
    }
    result = result || { error: '서버가 결과를 보내지 않았어요' };
    const now = LIVE.find(k => state.stages[k] === 'now');
    if (result.error){ if (now) state.stages[now] = 'fail'; }
    else LIVE.forEach(k => { state.stages[k] = 'done'; });
    if (!canBuild(result)) state.stages.ir = 'off';
    state.result = result;
    renderSteps(); renderResult();          // 시나리오 이름은 사용자가 적는다 — 자동으로 채우지 않는다 (2026-11-12)
    return canBuild(result);
  }

  /* 시나리오 생성 옵션 — 중지조건 · 재시도는 늘 켬, 압축 1 · 2 는 사용자가 고른다 (2026-11-12). 고른 값은 브라우저에 기억 */
  function genOptions(){
    const o = { stop_retry: true };
    document.querySelectorAll('[data-fin-opt]').forEach(c => { o[c.dataset.finOpt] = c.checked; });
    return o;
  }

  /* ── 시나리오 생성 (혜정 IR) — 검토 전 초안 → IR. 단계가 끝날 때마다 그 단계 입력값을 채운다 ── */
  async function buildIr(){
    Object.assign(state, { handoff: null, irSteps: {}, irTotal: 0, ir: null, irFile: null, irError: null });
    state.stages.ir = 'now'; renderSteps(); renderResult();
    try {
      const h = await post('/api/review-draft', { selection_hash: state.result.gate.selection_hash });
      if (!h.filename) throw new Error(h.error || '초안을 만들지 못했어요');
      state.handoff = h; state.irTotal = (h.steps || []).length;
      renderSteps(); renderResult();
      const res = await fetch('/api/scenario-ir-drafts', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/x-ndjson' },
        body: JSON.stringify({ approved_filename: h.filename, generation_options: genOptions() }) });
      let done = null, fail = null;
      const plain = await readLines(res, ev => {
        if (ev.event === 'scenario_steps') state.irTotal = (ev.steps || []).length || state.irTotal;
        else if (ev.event === 'step_preview' && ev.step){ state.irSteps[ev.step_id] = ev.step; renderSteps(); renderResult(); }
        else if (ev.event === 'generation_complete') done = ev.result;
        else if (ev.event === 'generation_error') fail = ev.error || '생성 실패';
      });
      done = done || (plain && plain.ir ? plain : null);
      if (!done) throw new Error(fail || (plain && plain.error) || '서버가 결과를 보내지 않았어요');
      state.ir = done.ir; state.irFile = done.file;
      (done.ir.tasks || []).forEach(t => (t.steps || []).forEach(s => { state.irSteps[s.step_id] = s; }));   // 최종 검증 뒤 고친 값
      state.stages.ir = 'done';
    } catch (e){
      state.irError = e.message; state.stages.ir = 'fail';
    }
    renderSteps(); renderResult();
  }

  /* ── 승인 · 등록 ── */
  async function register(){
    const name = $('finName').value.trim(), who = ($('finWho') || {}).value ? $('finWho').value.trim() : '';
    if (!name){ state.regError = '시나리오 이름을 적으세요.'; renderResult(); $('finName').focus(); return; }
    if (!who){ state.regError = '승인자를 적으세요.'; renderResult(); $('finWho').focus(); return; }
    state.regBusy = true; state.regError = null; renderResult();
    try {
      const j = await post('/api/register', { selection_hash: state.result.gate.selection_hash, name, approver: who,
        steps: Object.keys(state.checked).filter(k => state.checked[k]), review_file: state.handoff.filename, ir_file: state.irFile });
      store.set('tdg.approver', who);
      state.registered = j.scenario;
      regs.unshift(j.scenario);
      renderList();
    } catch (e){ state.regError = '등록하지 못했어요: ' + e.message; }
    state.regBusy = false; renderResult();
  }

  /* ── 실행 — 버튼 잠금 · 새로고침 경고 ── */
  const leaving = e => { e.preventDefault(); e.returnValue = ''; };
  async function run(work){
    if (state.busy) return;
    state.busy = true; $('finRun').disabled = true;
    $('finOut').setAttribute('aria-busy', 'true');
    window.addEventListener('beforeunload', leaving);     // 새로고침 · 창 닫기만 진행을 끊는다 — 메뉴 이동은 계속 돈다
    try { await work(); }
    finally {
      state.busy = false; $('finRun').disabled = false;
      $('finOut').removeAttribute('aria-busy');
      window.removeEventListener('beforeunload', leaving);
      renderResult();
    }
  }
  function say(msg){ const m = $('finMsg'); if (m){ m.textContent = msg; m.hidden = !msg; } }
  function analyze(){
    if (state.busy) return;
    const utt = $('finUtt').value.trim();
    if (!utt){ say('자연어 요청을 입력하세요.'); $('finUtt').focus(); return; }
    if (!SERVER){ say('로컬 서버(tap.cli serve)로 열었을 때 분석할 수 있어요.'); return; }
    say('');
    if (state.registered) $('finName').value = '';     // 등록을 끝낸 뒤 새로 분석 — 이름도 새로
    state = fresh(); viewing = null;
    renderList();
    return run(async () => { if (await select(utt)) await buildIr(); });
  }

  /* ── 화면 ── */
  function show(){ renderList(); renderSteps(); renderResult(); }
  function mount(){
    $('finRun').addEventListener('click', analyze);
    $('finUtt').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) analyze(); });
    document.querySelectorAll('[data-fin-opt]').forEach(c => {
      c.checked = store.get('tdg.opt.' + c.dataset.finOpt) === '1';
      c.addEventListener('change', () => store.set('tdg.opt.' + c.dataset.finOpt, c.checked ? '1' : ''));
    });
  }
  mount();
  window.FinalReg = { show, state: () => state, paramTable };
  if (typeof S !== 'undefined' && S.view === 'reg') show();
})();
