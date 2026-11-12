/* 시나리오 실행 — 최종 화면 (2026-11-12, P4)
   최종 '시나리오 등록'에서 승인 · 등록한 시나리오(TAP.registered)를 골라 실행한다. 실행기 연결 전이라 드라이런만:
   API 를 부르지 않고 IR 로 요청(Baseline 에 입력값을 덮은 XML)을 만들어 실행 이력(data/runs)에 남긴다.
   되돌릴 수 없는 단계(R2)는 승인본과 별개로 실행할 때마다 확인한다 — 서버가 다시 확인 (POST /api/registered/run).
   offline-ui.html 의 실행 메뉴 함수(renderRunList · renderRunStage)를 실서버 모드에서만 바꿔 끼운다. */
(function(){
  'use strict';
  if (typeof TAP === 'undefined' || !TAP) return;
  TAP.registered = TAP.registered || [];
  TAP.runs = TAP.runs || [];
  const R = { rows: [], confirm: {}, result: null, error: null, busy: false };

  const $ = id => document.getElementById(id);
  const regOf = id => TAP.registered.find(s => s.id === id);
  const stale = s => s.catalog_version != null && TAP.build && TAP.build.catalog_version != null && s.catalog_version !== TAP.build.catalog_version;
  const apiCode = id => shortApi(id).split('/').pop().replace(/\.do$/, '');
  const needs = s => (s.confirm_steps || []).length > 0;
  const ready = () => R.rows.length && R.rows.every(r => { const s = regOf(r.id); return s && !stale(s) && (!needs(s) || R.confirm[r.key]); });

  renderRunList = function(){
    const q = (S.runSearch || '').trim();
    const list = TAP.registered.filter(s => !q || (s.name || '').includes(q) || (s.utterance || '').includes(q));
    $('runList').innerHTML = list.map(s => `<li><button class="sitem" type="button" data-pick="${esc(s.id)}" ${stale(s) ? 'disabled' : ''} style="width:100%;text-align:left">
        <b>${esc(s.name)}</b><span class="note" style="display:block">단계 ${s.steps}${s.irreversible ? ` · 되돌릴 수 없는 단계 ${s.irreversible}` : ''}`
        + `${stale(s) ? ' · <span style="color:var(--signal)">재승인 필요</span>' : ''}</span></button></li>`).join('')
      || `<li class="nodata" style="list-style:none">${TAP.registered.length ? '찾는 시나리오가 없습니다.' : '등록된 시나리오가 없습니다. 시나리오 등록에서 승인하고 등록하면 여기에 나타납니다.'}</li>`;
    $('runList').querySelectorAll('[data-pick]').forEach(b => b.addEventListener('click', () => {
      R.rows.push({ key: 'r' + Date.now() + Math.random(), id: b.dataset.pick, n: 1 }); R.result = null; R.error = null; renderRunStage();
    }));
  };

  function resultHtml(run){
    const groups = [];
    run.calls.forEach(c => { const k = `${c.scenario_id}#${c.k}`; let g = groups.find(x => x.k === k);
      if (!g) groups.push(g = { k, title: `${c.scenario}${run.rows.find(r => r.scenario_id === c.scenario_id).count > 1 ? ` #${c.k}` : ''}`, calls: [] }); g.calls.push(c); });
    return `<div class="card fade" style="margin-top:12px"><div class="card-hd hd-row"><h2 class="sm">드라이런 결과</h2>`
      + `<span class="fin-sum">요청 ${run.calls.length}건 · 실제 API 는 호출하지 않았어요</span></div>`
      + groups.map(g => `<section class="fin-task"><div class="fin-th"><b>${esc(g.title)}</b></div><ol class="fin-list">${g.calls.map((c, i) =>
          `<li><span class="fin-kind"><b>${i + 1}</b></span><div class="fin-sb"><div class="fin-edge">${esc(c.name || '')}</div>`
          + `<span class="fin-api mono">${esc(apiCode(c.api_id || ''))}</span>`
          + window.FinalReg.paramTable(c.api_id, c.inputs, c.bindings)
          + (c.xml ? `<details class="fin-memo"><summary>보낼 요청 XML</summary><pre class="run-xml">${esc(c.xml)}</pre></details>` : '')
          + `</div><div class="fin-bs">${c.tier === 'R2' ? '<span class="fin-badge warn-b">되돌릴 수 없음</span>' : ''}</div></li>`).join('')}</ol></section>`).join('')
      + (run.unresolved.length ? `<details class="fin-memo"><summary>메모 ${run.unresolved.length}개</summary><ul>${run.unresolved.map(u => `<li>${esc(u)}</li>`).join('')}</ul></details>` : '')
      + `<p class="fin-done">✓ 실행 이력에 남겼어요</p><div class="btn-row"><button class="btn btn-ghost btn-sm" type="button" id="runToHist">실행 이력 보기</button></div></div>`;
  }

  renderRunStage = function(){
    const rows = R.rows;
    const confirmList = rows.filter(r => { const s = regOf(r.id); return s && needs(s); });
    $('runStage').innerHTML = `<div class="card"><div class="card-hd"><h2 class="sm">선택된 시나리오 <span class="cnt">(${rows.length})</span></h2></div>
      ${rows.length ? `<div class="tbl-wrap"><table><thead><tr><th>#</th><th>시나리오</th><th>단계</th><th>반복</th><th></th></tr></thead><tbody>${rows.map((r, i) => { const s = regOf(r.id);
        return `<tr><td class="v">${i + 1}</td><td style="font-size:13px">${esc(s ? s.name : '삭제된 시나리오')}${s && stale(s) ? ' <span class="st st-rb">재승인 필요</span>' : ''}</td>
          <td class="v">${s ? s.steps : '—'}${s && s.irreversible ? ` <span class="fin-badge warn-b">R2 ${s.irreversible}</span>` : ''}</td>
          <td><input type="text" inputmode="numeric" data-n="${r.key}" value="${r.n}" style="width:60px" aria-label="반복 횟수"></td>
          <td class="acts"><button class="xlink" type="button" data-rm="${r.key}">빼기</button></td></tr>`; }).join('')}</tbody></table></div>
        ${confirmList.length ? `<div class="fin-approve"><h3>이번 실행에서 확인 <span class="cnt">${confirmList.length}</span></h3><ul class="fin-chk">${confirmList.map(r => { const s = regOf(r.id);
          return `<li><label><input type="checkbox" data-rc="${r.key}" ${R.confirm[r.key] ? 'checked' : ''}> <b>${esc(s.name)}</b> 되돌릴 수 없는 단계를 실행해도 돼요</label>`
            + `<span class="fin-why">${s.confirm_steps.map(c => esc(c.edge || c.key)).join(' · ')}</span></li>`; }).join('')}</ul>
          <p class="fin-why">되돌릴 수 없는 단계는 승인과 별개로 실행할 때마다 확인해요.</p></div>` : ''}
        <div class="btn-row"><button class="btn btn-primary" id="runDry" type="button" ${ready() && !R.busy ? '' : 'disabled'}>${R.busy ? '만드는 중…' : '드라이런'}</button>
          <button class="btn btn-ghost" type="button" disabled title="실행기 · 개발 서버 인증 연결 전">실행 (연결 전)</button></div>
        ${R.error ? `<p class="fin-err">${esc(R.error)}</p>` : ''}`
      : `<p class="nodata">왼쪽에서 시나리오를 누르면 담깁니다.${TAP.registered.length ? '' : ' 아직 등록된 시나리오가 없습니다.'}</p>`}</div>
      ${R.result ? resultHtml(R.result) : ''}`;
    const st = $('runStage');
    st.querySelectorAll('[data-rm]').forEach(b => b.addEventListener('click', () => {
      R.rows = R.rows.filter(r => r.key !== b.dataset.rm); delete R.confirm[b.dataset.rm]; R.result = null; R.error = null; renderRunStage(); }));
    st.querySelectorAll('[data-n]').forEach(inp => inp.addEventListener('change', () => {
      const r = R.rows.find(x => x.key === inp.dataset.n), v = Math.max(1, Math.min(20, parseInt(inp.value, 10) || 1));
      if (r){ r.n = v; inp.value = v; R.result = null; }
    }));
    st.querySelectorAll('[data-rc]').forEach(c => c.addEventListener('change', () => {
      R.confirm[c.dataset.rc] = c.checked; const b = $('runDry'); if (b) b.disabled = !ready() || R.busy; }));
    const dry = $('runDry');
    if (dry) dry.addEventListener('click', dryRun);
    const toHist = $('runToHist');
    if (toHist) toHist.addEventListener('click', () => setView('hist'));
  };

  async function dryRun(){
    if (R.busy || !ready()) return;
    R.busy = true; R.error = null; R.result = null; renderRunStage();
    const items = R.rows.map(r => { const s = regOf(r.id);
      return { id: r.id, n: r.n, confirm: needs(s) && R.confirm[r.key] ? s.confirm_steps.map(c => c.key) : [] }; });
    try {
      const res = await fetch('/api/registered/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items }) });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.error || `서버 오류 (${res.status})`);
      R.result = j.run; TAP.runs.unshift(j.run);
      R.confirm = {};                                   // 다음 실행에서 다시 확인
    } catch (e){ R.error = '드라이런을 하지 못했어요: ' + e.message; }
    R.busy = false; renderRunStage();
  }

  if (typeof S !== 'undefined' && S.view === 'run'){ renderRunList(); renderRunStage(); }
})();
