/* 상태 그래프 만들기 — 업무 담당자용 캔버스 편집기.
 *
 * 업무 담당자는 상태 · 화살표 · 업무 이름만 정한다 (노드 흐름). API 와 '조회로 찾을 수 있는 상태'는 이 화면에서 다루지 않는다 —
 * 시나리오를 만들 때 ② 경로 탐색 · ③ API 선택이 API Metadata 에서 정하고 승인본에 고정한다.
 * matchEdge · matchLookup · reviewItems 는 개발 담당자 검수 목록(관리자 › 전사)에서만 쓴다.
 *
 * 데이터: window.TAP_DATA (tap.cli ui-data 로 생성). 쓰는 법:
 *   GraphEditor.mount(element, { domain: 'od' | null, embedded: false })
 */
(function () {
  "use strict";

  const CSS = `
  .ge{--ai:#7C3AED;--ai-soft:#F3EEFE;--grid:#E4E9F0;display:grid;gap:12px;font-size:14px;line-height:1.6;color:var(--ink)}
  @media (prefers-color-scheme: dark){:root:not([data-theme="light"]) .ge{--ai:#B69CFF;--ai-soft:#231A3A;--grid:#1D232C}}
  :root[data-theme="dark"] .ge{--ai:#B69CFF;--ai-soft:#231A3A;--grid:#1D232C}
  .ge *{box-sizing:border-box}
  .ge h2,.ge h3{margin:0;letter-spacing:-.01em;text-wrap:balance}
  .ge p{margin:0}
  .ge .mono{font-family:var(--mono)}
  .ge .note{font-size:12.5px;color:var(--muted)}
  .ge .lbl{font-size:11.5px;letter-spacing:.04em;color:var(--muted);font-weight:500}
  .ge .bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px}
  .ge .bar h1{font-size:19px;font-weight:600;margin:0}
  .ge .crumb{font-size:12px;color:var(--muted)}
  .ge .gsel{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .ge .gsel select{min-width:220px}
  .ge .scope{display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-left:auto}
  .ge .dchip{border:1px solid var(--hair);background:var(--panel);color:var(--ink-2);border-radius:999px;padding:2px 10px;font-size:12px;cursor:pointer}
  .ge .dchip[aria-pressed="true"]{background:var(--accent-soft);color:var(--accent);border-color:var(--accent);font-weight:600}
  .ge .counts{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
  .ge .st{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:1px 8px;border-radius:999px;white-space:nowrap;letter-spacing:0}
  .ge .st-ok{background:var(--accent-soft);color:var(--accent)}
  .ge .st-ai{background:var(--ai-soft);color:var(--ai)}
  .ge .st-none{background:var(--signal-soft);color:var(--signal)}
  .ge .st-ext{background:var(--panel-3);color:var(--muted)}
  .ge .st-err{background:var(--danger-soft);color:var(--danger)}
  .ge .st-good{background:var(--good-soft);color:var(--good)}
  .ge .gbtn{border:1px solid var(--hair);background:var(--panel);color:var(--ink);border-radius:7px;padding:6px 12px;font-size:13px;cursor:pointer;font-family:var(--sans);line-height:1.4}
  .ge .gbtn:hover{border-color:var(--muted)}
  .ge .gbtn.pri{background:var(--accent);border-color:var(--accent);color:var(--panel);font-weight:600}
  .ge .gbtn.ai{border-color:var(--ai);color:var(--ai);background:var(--ai-soft);font-weight:600}
  .ge .gbtn.dng{color:var(--danger)}
  .ge .gbtn[disabled]{opacity:.45;cursor:not-allowed}
  .ge .gbtn.sm{padding:3px 9px;font-size:12px}
  .ge .gbtn.ghost{background:transparent;border-color:transparent;color:var(--muted)}
  .ge .gbtn.ghost:hover{color:var(--ink);border-color:var(--hair)}
  .ge .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  .ge .work{display:grid;grid-template-columns:200px minmax(0,1fr) 330px;gap:12px;align-items:start}
  @media (max-width:1240px){.ge .work{grid-template-columns:190px minmax(0,1fr)} .ge .insp{grid-column:1/-1}}
  @media (max-width:760px){.ge .work{grid-template-columns:minmax(0,1fr)}}
  .ge .gcard{background:var(--panel);border:1px solid var(--hair-2);border-radius:10px;padding:14px 16px;min-width:0}
  .ge.embedded .gcard{background:var(--panel-2)}
  .ge .pal{display:grid;gap:8px;padding:12px}
  .ge .pal h2{font-size:14px;font-weight:600}
  .ge .plist{display:grid;gap:4px;max-height:540px;overflow-y:auto;padding-right:2px}
  @media (max-width:760px){.ge .plist{grid-auto-flow:column;grid-auto-columns:150px;max-height:none;overflow-x:auto;overflow-y:hidden;padding-bottom:4px}}
  .ge .pitem{display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:center;text-align:left;border:1px solid var(--hair-2);background:var(--panel);border-radius:7px;padding:6px 9px;cursor:grab;color:var(--ink);font-size:13px;user-select:none;font-family:var(--sans)}
  @media (pointer:fine){.ge .pitem{touch-action:none}}
  .ge .pitem:hover{border-color:var(--accent)}
  .ge .pitem .mono{font-size:12px;color:var(--muted)}
  .ge .pitem.placed{cursor:default;opacity:.5;border-style:dashed}
  .ge-ghost{position:fixed;z-index:200;pointer-events:none;background:var(--panel);border:2px solid var(--accent);border-radius:8px;padding:6px 12px;font-size:13px;box-shadow:0 6px 18px rgba(0,0,0,.18);transform:translate(-50%,-50%);color:var(--ink);font-family:var(--sans)}
  .ge-ghost b{font-family:var(--mono);margin-right:6px}
  .ge .cv{padding:0;overflow:hidden}
  .ge .coach{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) auto;gap:10px;align-items:start;padding:10px 14px;border-bottom:1px solid var(--hair-2);background:var(--accent-soft)}
  @media (max-width:900px){.ge .coach{grid-template-columns:minmax(0,1fr) auto}}
  .ge .tipx{display:grid;grid-template-columns:22px 1fr;gap:8px;font-size:12.5px;color:var(--ink-2);line-height:1.5}
  .ge .tipx b.n{display:grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--accent);color:var(--panel);font-size:12px;font-family:var(--mono)}
  .ge .stage{position:relative;overflow-x:auto;background:var(--panel-2)}
  .ge .stage svg{display:block;width:100%;min-width:760px;height:auto;touch-action:pan-x pan-y;user-select:none}
  .ge .stage svg.over{outline:2px dashed var(--accent);outline-offset:-6px}
  .ge .node{cursor:move;touch-action:none}
  .ge .node text{pointer-events:none}
  .ge .port{cursor:crosshair;touch-action:none}
  .ge .port:hover circle.ring{r:9}
  .ge .hit{cursor:pointer}
  .ge .xbtn{cursor:pointer}
  .ge .xbtn:hover circle{fill:var(--danger-soft)}
  .ge .emptyhint{position:absolute;inset:0;display:grid;place-items:center;pointer-events:none;color:var(--muted);font-size:14px}
  .ge .legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--muted);padding:8px 14px;border-top:1px solid var(--hair-2)}
  .ge .legend span{display:inline-flex;align-items:center;gap:6px}
  .ge .sw{display:inline-block;width:20px;border-top:2px solid}
  .ge .insp{display:grid;gap:12px;align-content:start}
  .ge .insp h2{font-size:15px;font-weight:600}
  .ge .insp h3{font-size:13px;font-weight:600}
  .ge .form{display:grid;gap:10px}
  .ge .fld{display:grid;gap:4px;min-width:0}
  .ge .fld label,.ge .fld .q{font-size:12.5px;color:var(--ink-2);font-weight:500}
  .ge .fld .hint{font-size:11.5px;color:var(--muted)}
  .ge .two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px}
  .ge select,.ge input[type="text"],.ge input[type="search"]{width:100%;min-width:0;font-family:var(--sans);font-size:13px;color:var(--ink);background:var(--panel);border:1px solid var(--hair);border-radius:7px;padding:6px 9px}
  .ge .box{border:1px solid var(--hair-2);border-radius:8px;padding:10px 12px;background:var(--panel-2);display:grid;gap:6px;font-size:13px}
  .ge .box.ai{border-color:var(--ai);background:var(--ai-soft)}
  .ge .box.ai b.t{color:var(--ai)}
  .ge .box.warn{border-color:var(--signal);background:var(--signal-soft)}
  .ge .ev{font-size:12.5px;color:var(--ink-2)}
  .ge .cands{display:grid;gap:6px}
  .ge .cand{display:grid;gap:3px;border:1px solid var(--hair-2);border-radius:7px;padding:7px 10px;background:var(--panel)}
  .ge .cand.top{border-color:var(--accent)}
  .ge .cand .hd{display:flex;justify-content:space-between;gap:8px;align-items:baseline;flex-wrap:wrap}
  .ge .cand .hd b{font-size:13px}
  .ge .cand .sel{font-family:var(--mono);font-size:12px;color:var(--ink-2)}
  .ge .cand .why{font-size:11.5px;color:var(--muted)}
  .ge .meter{height:4px;border-radius:2px;background:var(--panel-3);overflow:hidden}
  .ge .meter i{display:block;height:100%;background:var(--accent)}
  .ge .roles{display:grid;gap:6px}
  .ge .role{display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:start;border:1px solid var(--hair-2);border-radius:7px;padding:7px 10px;cursor:pointer;font-size:13px}
  .ge .role input{margin-top:4px}
  .ge .role span i{display:block;font-style:normal;font-size:11.5px;color:var(--muted)}
  .ge .role:has(input:checked){border-color:var(--accent);background:var(--accent-soft)}
  .ge .todo{display:grid;gap:5px}
  .ge .todo button{display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:start;text-align:left;border:1px solid var(--hair-2);background:var(--panel);border-radius:7px;padding:7px 10px;font-size:12.5px;cursor:pointer;color:var(--ink);line-height:1.5;font-family:var(--sans)}
  .ge .todo button:hover{border-color:var(--accent)}
  .ge .qs{display:grid;gap:6px}
  .ge .qq{display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:start;font-size:12.5px}
  .ge .qq input{margin-top:3px}
  .ge .qq.done span{color:var(--muted);text-decoration:line-through}
  .ge details summary{cursor:pointer;font-size:13px;font-weight:600}
  .ge .lower{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:start}
  @media (max-width:1100px){.ge .lower{grid-template-columns:minmax(0,1fr)}}
  .ge .lower h2{font-size:15px;font-weight:600}
  .ge .path{font-family:var(--mono);font-size:12.5px;line-height:1.8}
  .ge .dev{display:grid;gap:6px}
  .ge .dev button{display:grid;grid-template-columns:auto 1fr;gap:8px;text-align:left;border:1px solid var(--hair-2);background:var(--panel);border-radius:7px;padding:7px 10px;font-size:12.5px;cursor:pointer;color:var(--ink);font-family:var(--sans);line-height:1.5}
  .ge pre.yaml{margin:0;font-family:var(--mono);font-size:12px;line-height:1.6;background:var(--panel-2);border:1px solid var(--hair-2);border-radius:8px;padding:12px;overflow:auto;color:var(--ink-2);max-height:320px}
  .ge-toast{position:fixed;left:50%;transform:translateX(-50%);bottom:calc(20px + env(safe-area-inset-bottom, 0px));background:var(--ink);color:var(--panel);padding:8px 14px;border-radius:8px;font-size:13px;max-width:calc(100% - 32px);z-index:210;font-family:var(--sans)}
  .ge .emptyst{display:grid;gap:10px;justify-items:start;padding:24px 18px}
  .ge .prog{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;font-size:13px;color:var(--ink-2)}
  .ge .prog b{font-weight:600}
  .ge .prog .need{border:0;background:var(--signal-soft);color:var(--signal);font-weight:600;border-radius:999px;padding:1px 10px;font-size:12.5px;cursor:pointer;font-family:var(--sans)}
  .ge .prog .need[disabled]{background:var(--good-soft);color:var(--good);cursor:default}
  .ge .more{position:relative;margin-left:auto}
  .ge .menu{position:absolute;right:0;top:calc(100% + 4px);z-index:30;min-width:220px;display:grid;padding:6px;background:var(--panel);border:1px solid var(--hair);border-radius:9px;box-shadow:0 8px 24px rgba(0,0,0,.14)}
  .ge .menu button{text-align:left;border:0;background:transparent;color:var(--ink);font-size:13px;padding:7px 10px;border-radius:6px;cursor:pointer;font-family:var(--sans)}
  .ge .menu button:hover{background:var(--panel-2)}
  .ge .menu hr{border:0;border-top:1px solid var(--hair-2);margin:4px 2px}
  .ge .stage .emptyhint span{max-width:44ch;text-align:center;line-height:1.7}
  .ge.ge-ov{position:fixed;inset:0;z-index:220;display:grid;place-items:center;padding:20px;background:rgba(15,20,30,.45)}
  .ge .ge-box{width:min(760px,100%);max-height:86vh;overflow:auto;background:var(--panel);border-radius:12px;padding:16px 18px;display:grid;gap:12px;box-shadow:0 16px 48px rgba(0,0,0,.25)}
  .ge .ge-mh{display:flex;justify-content:space-between;align-items:center;gap:10px}
  .ge .ge-mh h2{font-size:16px;font-weight:600}
  `;

  const DOMS = { pd: "상품", od: "주문", ds: "물류" };
  const PLACEHOLDERS = [];                       // 공통코드를 받기 전인 그래프 자리 — 지금은 없음 (받은 그룹은 '새 그래프' 에서 고른다)
  const VB = { w: 1100, h: 560 }, NW = 124, NH = 52;
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const short = p => p ? String(p).split("/").pop() : "";
  const key = (a, b) => `${a}>${b}`;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const snap = v => Math.round(v / 5) * 5;
  const selTxt = s => Object.entries(s || {}).map(([k, v]) => `${k}=${v}`).join(", ");

  /* ------------------------------------------------ API 후보 찾기 — src/tap/graph/match.py 와 같은 규칙 */
  const FOUND = 0.75, CHECK = 0.45, REV = ["취소", "반려", "철회", "삭제", "해제", "중지"];
  function norm(s){
    s = String(s || "").replace(/\([^)]*\)/g, "").replace(/[\s·,\/\-_\[\]]+/g, "");
    if (s.endsWith("처리")) s = s.slice(0, -2);
    if (s.endsWith("만")) s = s.slice(0, -1);
    return s;
  }
  function bigrams(s){ const out = new Set(); for (let i = 0; i < s.length - 1; i++) out.add(s.slice(i, i + 2)); return out.size ? out : new Set([s]); }
  function sim(a, b){
    const x = norm(a), y = norm(b);
    if (!x || !y) return 0;
    if (x === y) return 1;
    let base;
    if (x.includes(y) || y.includes(x)) base = 0.8 * Math.pow(Math.min(x.length, y.length) / Math.max(x.length, y.length), 0.25);
    else { const bx = bigrams(x), by = bigrams(y); let n = 0; bx.forEach(g => { if (by.has(g)) n++; }); base = 0.7 * 2 * n / (bx.size + by.size); }
    if (REV.some(w => x.includes(w) !== y.includes(w))) base *= 0.5;
    return base;
  }
  function best(q, texts){ let b = 0, why = ""; for (const [l, t] of texts){ const s = sim(q, t); if (s > b){ b = s; why = `${l} '${t}'`; } } return [b, why]; }
  /* 1순위와 같은 점수의 다른 API 가 있으면 고를 수 없으니 '확인 필요' (예: 회수처리 · 티켓 회수처리) */
  const tieOf = c => c.length > 1 && c[1].api !== c[0].api && Math.abs(c[1].score - c[0].score) < 1e-9;
  const statusOf = c => !c.length || c[0].score < CHECK ? "없음" : c[0].score >= FOUND && !c[0].unknown && !tieOf(c) ? "찾음" : "확인 필요";
  const sortC = c => c.sort((a, b) => b.score - a.score || (a.unknown - b.unknown) || (a.api < b.api ? -1 : 1)).filter(x => x.score >= 0.3).slice(0, 3);

  const stateFilter = (fields, f) => f ? [...fields].find(x => x.toLowerCase() === f.toLowerCase() || x.toLowerCase() === f.toLowerCase() + "in") || null : null;
  function matchEdge(D, name, toName, doms, field, toCode){
    const q = name || toName, out = [], req = new Map(D.ops.map(o => [o.id, new Set(o.req.map(r => r[0]))]));
    for (const m of D.metadata){
      if (m.kind !== "write" || m.tool_enabled === false || (doms.length && !doms.includes(m.domain))) continue;
      const sf = toCode ? stateFilter(req.get(m.api_id) || new Set(), field) : null;
      if (sf && sf === field){
        const [s0] = best(q, [["API 이름", m.api_name]]);
        if (["등록", "생성"].includes(m.action)) out.push({ api: m.api_id, apiName: m.api_name, sel: { [sf]: toCode }, score: 0.6, why: [`요청에 상태 필드 ${sf} 가 있지만 새로 ${m.action}하는 API — 기존 데이터의 상태를 바꾸는 데는 맞지 않을 수 있음`] });
        else out.push({ api: m.api_id, apiName: m.api_name, sel: { [sf]: toCode }, score: Math.max(0.85, Math.min(1, s0 + 0.1)), why: [`요청에 상태 필드 ${sf} 가 있어 도착 상태 코드 ${toCode} 를 넣어 바로 바꿈`] });
        continue;
      }
      const apiT = [["API 이름", m.api_name], ...(m.aliases || []).map(a => ["API 별칭", a])];
      const bonus = norm(toName) && norm(m.search_text).includes(norm(toName)) ? 0.08 : 0;
      const sels = m.selectors || [];
      if (!sels.length){ const [s, w] = best(q, apiT); out.push({ api: m.api_id, apiName: m.api_name, sel: {}, score: Math.min(1, s + bonus), why: [w ? `${w} 과(와) 비슷함` : "이름이 비슷하지 않음"] }); continue; }
      for (const sel of sels){
        for (const v of sel.values){
          const texts = (v.name ? [["구분값 이름", v.name]] : []).concat((v.aliases || []).map(a => ["구분값 별칭", a]));
          let [s, w] = best(q, texts);
          if (s < CHECK){ const [s2, w2] = best(q, apiT); if (s2 * 0.8 > s){ s = s2 * 0.8; w = w2; } }
          out.push({ api: m.api_id, apiName: m.api_name, sel: { [sel.field]: v.value }, action: v.name, score: Math.min(1, s + bonus),
            why: [w ? `${w} 과(와) 비슷함` : "이름이 비슷하지 않음"].concat(v.source === "override" ? ["개발 담당자가 확인한 구분값"] : []) });
        }
        if (!sel.complete){
          const [s, w] = best(q, apiT.concat(sel.values.filter(v => v.name).map(v => ["구분값 이름", v.name])));
          out.push({ api: m.api_id, apiName: m.api_name, sel: { [sel.field]: "?" }, score: Math.min(1, s * 0.85 + bonus), unknown: true,
            why: [w ? `${w} 과(와) 비슷함` : "이름이 비슷하지 않음", `${sel.field} 값 목록이 미완성 — 개발 담당자가 값을 확인해야 함`] });
        }
      }
    }
    return sortC(out);
  }
  function matchLookup(D, stateName, code, field, doms){
    const res = new Map(D.ops.map(o => [o.id, new Set(o.res.map(r => r[0]))])), req = new Map(D.ops.map(o => [o.id, new Set(o.req.map(r => r[0]))])), out = [];
    for (const m of D.metadata){
      if (m.kind !== "read" || m.tool_enabled === false || (doms.length && !doms.includes(m.domain))) continue;
      if (field && !(res.get(m.api_id) || new Set()).has(field)) continue;
      const sels = m.selectors || [];
      const sf = stateFilter(req.get(m.api_id) || new Set(), field);
      if (sf){
        out.push({ api: m.api_id, apiName: m.api_name, sel: { [sf]: code }, score: 0.9, why: [`요청에 상태 필드 ${sf} 가 있어 코드 ${code} 로 바로 거름`] });
        continue;
      }
      if (!sels.length){ out.push({ api: m.api_id, apiName: m.api_name, sel: {}, score: 0.35, why: [`응답에 ${field} 가 있지만 상태로 걸러 주는 값이 없음 — 전체를 조회해 골라야 함`] }); continue; }
      for (const sel of sels){
        for (const v of sel.values){
          const nm = v.name || "", inner = (nm.match(/\(([^)]*)\)/) || [])[1] || "", codes = inner.match(/\d+/g) || [];
          let [s, w] = best(stateName, [["구분값 이름", nm]].concat((v.aliases || []).map(a => ["구분값 별칭", a])));
          const why = w ? [`${w} 과(와) 비슷함`] : [];
          if (codes.includes(code)){ s = Math.max(s, codes.length === 1 ? 0.9 : 0.8); why.push(`구분값 이름에 코드 ${code} 가 있음` + (codes.length === 1 ? "" : " (다른 상태와 함께 조회)")); }
          out.push({ api: m.api_id, apiName: m.api_name, sel: { [sel.field]: v.value }, action: nm || null, score: s, why: why.length ? why : ["이름이 비슷하지 않음"] });
        }
        if (!sel.complete) out.push({ api: m.api_id, apiName: m.api_name, sel: { [sel.field]: "?" }, score: 0.35 + 0.15 * sim(stateName, m.api_name), unknown: true,
          why: [`응답에 ${field} 가 있음`, `${sel.field} 값 목록이 미완성 — 개발 담당자 확인`] });
      }
    }
    return sortC(out);
  }

  /* ------------------------------------------------ 편집기 */
  let SEQ = 0;
  function mount(root, opts){
    opts = Object.assign({ domain: null, embedded: false }, opts || {});
    const D = window.TAP_DATA;
    if (!document.getElementById("ge-style")){ const st = document.createElement("style"); st.id = "ge-style"; st.textContent = CSS; document.head.appendChild(st); }
    const P = "ge" + (++SEQ);
    const id = n => `${P}-${n}`;
    const el = n => document.getElementById(id(n));
    root.classList.add("ge"); if (opts.embedded) root.classList.add("embedded");
    if (!D){ root.innerHTML = `<div class="gcard emptyst"><h2>산출물이 없습니다</h2><p class="note">tap-data.js 를 먼저 만드세요: <span class="mono">PYTHONPATH=src python -m tap.cli ui-data</span></p></div>`; return; }

    /* 그래프 목록 = data/graphs 의 그래프 (화면에서 한 번 저장한 것은 drafts 로도 와서 배치까지 복원) + 공통코드 대기 */
    const fromK = (k, extra) => Object.assign({ id: k.graph.id, name: k.graph.name, dom: k.graph.domain, loaded: true, k }, extra || {});
    const GRAPHS = D.graphs.map(g => fromK(g));
    (D.drafts || []).forEach(dr => { if (!dr || !dr.graph) return; const g = GRAPHS.find(x => x.id === dr.graph.id);
      if (g) g.draft = dr; else GRAPHS.push(fromK(dr, { draft: dr, isNew: true })); });
    PLACEHOLDERS.filter(p => !GRAPHS.some(g => g.id === p.id)).forEach(p => GRAPHS.push(Object.assign({ loaded: false }, p)));
    const scopeDoms = () => opts.embedded ? ["pd", "od", "ds"] : S.doms;
    const MEM = {};                                 // 그래프를 바꿔도 그리던 내용 유지 (이 화면을 닫기 전까지)

    /* 상태 필드 추정 — 코드 그룹 ID 를 낙타 표기로 바꾼 이름이 조회 응답에 있으면 (SLITM_APRVL_GBCD → slitmAprvlGbcd) */
    function guessField(g){
      if (g.k.graph.state_field) return { v: g.k.graph.state_field, why: "그래프에 적힌 값" };
      const camel = g.k.code_group.id.toLowerCase().replace(/_([a-z0-9])/g, (_, c) => c.toUpperCase());
      for (const o of D.ops.filter(o => o.kind === "read"))
        for (const r of o.res) if (r[0].toLowerCase() === camel.toLowerCase() || r[0].toLowerCase().endsWith(camel.toLowerCase()))
          return { v: r[0], why: `조회 응답 필드 이름이 코드 그룹 ID 와 같음 (${o.sum})` };
      return { v: null, why: "코드 그룹 ID 와 같은 이름의 응답 필드가 없음" };
    }

    function initial(gid){
      const g = GRAPHS.find(x => x.id === gid) || GRAPHS[0];
      const base = { graph: g.id, doms: S0.doms || ["pd", "od", "ds"], coach: true, filter: "", nodes: {}, edges: [], q: {},
        stateField: { v: g.loaded ? guessField(g).v : null, st: "추정" }, sel: { kind: "none" },
        test: { from: "", target: "", must: "" }, saved: null, showYaml: false, server: S0.server, creating: false };
      if (g.draft) return fromDraft(g, base);
      return fromKnowledge(g, base);
    }
    /* 화면에서 저장한 적 없는 그래프(손으로 쓴 data/graphs 파일) — 시나리오 생성이 쓰는 것과 같은 그래프를 보여 준다 */
    function fromKnowledge(g, base){
      const k = g.k, ts = k.transitions || [], lks = k.lookups || [];
      if (!ts.length && !lks.length) return base;
      const order = c => Object.keys(k.code_group.codes).indexOf(c);
      const inT = [...new Set(ts.flatMap(t => [String(t.from), String(t.to)]))].sort((a, b) => order(a) - order(b));
      const onlyL = [...new Set(lks.flatMap(l => (l.states || []).map(String)))].filter(c => !inT.includes(c) && c in k.code_group.codes).sort((a, b) => order(a) - order(b));
      const nodes = {}, W = 180;
      inT.forEach((c, i) => { nodes[c] = { x: 110 + (i % 6) * W, y: 150 + Math.floor(i / 6) * 150, role: "api" }; });
      onlyL.forEach((c, i) => { nodes[c] = { x: 110 + (i % 6) * W, y: 420 + Math.floor(i / 6) * 110, role: "api" }; });
      const edges = ts.map(t => ({ from: String(t.from), to: String(t.to), name: t.name, st: "확정", origin: "사람이 확인한 그래프" }));
      return Object.assign(base, { nodes, edges, coach: false, stateField: k.graph.state_field ? { v: k.graph.state_field, st: "확정" } : base.stateField });
    }
    function fromDraft(g, base){
      const dr = g.draft, gg = dr.graph || {}, ent = (gg.entry_states || []).map(String), ext = (gg.external_states || []).map(String), nodes = {};
      void ent; void ext;
      Object.entries(dr.layout || {}).forEach(([c, xy]) => { nodes[String(c)] = { x: xy[0], y: xy[1], role: "api" }; });
      const edges = (dr.transitions || []).map(t => ({ from: String(t.from), to: String(t.to), name: t.name, st: "확정", origin: "저장본" }))
        .concat((dr.external_transitions || []).map(([a, b]) => ({ from: String(a), to: String(b), name: "", st: "확정", origin: "저장본" })));
      return Object.assign(base, { nodes, edges, coach: false, saved: dr.version ? { v: dr.version } : null,
        stateField: gg.state_field ? { v: gg.state_field, st: "확정" } : base.stateField });
    }
    const S0 = { server: false };
    let S = initial(opts.domain ? (GRAPHS.find(g => g.dom === opts.domain) || {}).id || "ORD_STAT_GBCD" : "ORD_STAT_GBCD");
    const switchTo = gid => { MEM[S.graph] = S; S0.doms = S.doms; S = MEM[gid] || initial(gid); S.creating = false; };

    /* 파생 값 */
    const graph = () => GRAPHS.find(x => x.id === S.graph);
    const CODES = () => { const g = graph(); if (!g || !g.loaded) return [];
      const t = (D.codes || []).find(x => x.id === g.k.code_group.id);      // 공통코드 테이블 전체가 있으면 그것 (저장본은 놓은 상태만 담음)
      const src = t || g.k.code_group, order = t && t.order ? t.order : Object.keys(src.codes);
      return order.map(c => [String(c), src.codes[c]]); };
    const ENT = () => (graph() && graph().k && graph().k.graph.entity) || "데이터";
    const eul = w => { const c = String(w).charCodeAt(String(w).length - 1); return w + (c >= 0xAC00 && c <= 0xD7A3 && (c - 0xAC00) % 28 ? "을" : "를"); };
    const NAME = c => (CODES().find(x => x[0] === c) || [])[1] || c;
    const ORDER = c => CODES().findIndex(x => x[0] === c);
    const sn = c => `${c} ${NAME(c)}`;
    const placed = () => Object.keys(S.nodes).sort((a, b) => ORDER(a) - ORDER(b));
    const edgeOf = k => S.edges.find(e => key(e.from, e.to) === k);
    const isExternal = e => S.nodes[e.from] && S.nodes[e.from].role === "ext";
    const workEdges = () => S.edges.filter(e => !isExternal(e));
    const entry = () => Object.keys(S.nodes).find(c => S.nodes[c].role === "entry") || "";

    function counts(){
      const w = workEdges();
      return { ok: w.filter(e => e.name).length, noname: w.filter(e => !e.name).length };
    }

    /* 할 일 · 검증 — 노드 흐름만 본다 (API 는 시나리오를 만들 때) */
    function issues(){
      const out = [], add = (lv, msg, sel, open) => out.push({ lv, msg, sel, open });
      for (const e of workEdges()){
        const sel = { kind: "edge", id: key(e.from, e.to) }, lab = `${NAME(e.from)} → ${NAME(e.to)}`;
        if (!e.name){ add("err", `${lab}: 이 변화를 업무에서 뭐라고 부르는지 적으세요.`, sel); continue; }
        if (!S.edges.some(r => r.from === e.to && r.to === e.from && r.name))
          add("warn", `${lab}: 되돌리는 화살표가 없어 실행 중 실패하면 이 단계는 되돌릴 수 없습니다 (권한 등급 R2 — 실행할 때마다 확인).`, sel);
      }
      if (S.stateField.st !== "확정") add("warn", S.stateField.v ? `현재 상태를 읽는 필드(${S.stateField.v})가 확정 전입니다 (자동 추정). '⋯ 더보기 › 그래프 설정'에서 확인하고 확정하세요.`
        : "현재 상태를 읽는 필드가 없습니다. '그래프 설정'에서 고르세요.", { kind: "none" }, "set");
      return out;
    }

    /* 시험해 보기 — 화살표만으로 출발 → 목표 경로 (어느 상태를 조회로 찾는지 · API 는 시나리오를 만들 때 정한다) */
    function search(start, target, must){
      const es = workEdges().filter(e => e.name), first = [start, must ? start === must : true], q = [[first, []]], seen = new Set([first.join()]);
      while (q.length){ const [[c, ok], path] = q.shift(); if (c === target && ok) return path; if (path.length >= 12) continue;
        for (const e of es.filter(e => e.from === c)){ const nx = [e.to, ok || e.to === must]; if (!seen.has(nx.join())){ seen.add(nx.join()); q.push([nx, [...path, e]]); } } }
      return null;
    }

    /* 뼈대 */
    function render(){
      const g = graph(), c = counts();
      const gs = GRAPHS.filter(x => opts.domain ? x.dom === opts.domain : S.doms.includes(x.dom));
      const opt = x => `<option value="${x.id}" ${x.id === S.graph ? "selected" : ""}>${esc(x.name)} · ${esc(x.id)}${x.loaded ? "" : " (공통코드 받기 전)"}</option>`;
      const graphOpts = opts.domain ? gs.map(opt).join("") : S.doms.map(d => { const l = GRAPHS.filter(x => x.dom === d);
        return `<optgroup label="${DOMS[d]} (${d})">${l.length ? l.map(opt).join("") : `<option disabled>그래프 없음</option>`}</optgroup>`; }).join("");
      if (opts.domain && !gs.length && !S.creating){
        root.innerHTML = `<div class="gcard emptyst"><span class="st st-ext">그래프 없음</span><h2>이 도메인이 주인인 상태 그래프가 없습니다</h2>
          <p class="note" style="max-width:62ch">이 도메인이 주인인 상태 코드 그룹을 받으면 여기서 그래프를 만들 수 있습니다.</p>
          <div class="row"><button class="gbtn" id="${id("newG")}">새 그래프</button>${(opts.actions || []).map((a, i) => `<button class="gbtn" data-act="${i}">${esc(a.label())}</button>`).join("")}</div></div>`;
        el("newG").onclick = () => { S.creating = true; render(); };
        root.querySelectorAll("[data-act]").forEach(b => b.onclick = () => opts.actions[+b.dataset.act].onClick());
        return;
      }
      root.innerHTML = `
        <div class="bar">
          ${opts.embedded ? `<div><h2 style="font-size:15px;font-weight:600">상태 그래프 만들기</h2></div>`
            : `<div><p class="crumb">관리자 › 도메인 › State Vocabulary</p><h1>상태 그래프 만들기</h1></div>`}
          <div class="gsel"><label class="lbl" for="${id("gs")}">그래프</label><select id="${id("gs")}">${graphOpts}</select><button class="gbtn sm" id="${id("newG")}">＋ 새 그래프</button></div>
          ${g.loaded && !S.creating ? `<div class="row" style="margin-left:auto"><button class="gbtn" id="${id("testB")}">시험해 보기</button><button class="gbtn pri" id="${id("saveB")}">저장</button></div>` : ""}
          ${opts.embedded ? "" : `<div class="scope"><span>1차 범위</span>${Object.entries(DOMS).map(([d, n]) => `<button class="dchip" data-dom="${d}" aria-pressed="${S.doms.includes(d)}">${n} <span class="mono">${d}</span></button>`).join("")}</div>`}
        </div>
        ${S.creating ? createCard() : g.loaded ? `
        <div class="prog" id="${id("counts")}"></div>
        <div class="work">
          <aside class="gcard pal" aria-label="공통코드">
            <h2>${esc(g.name)} <span class="mono" style="font-weight:400;color:var(--muted);font-size:12px">(${esc(g.k.code_group.id)})</span> · ${CODES().length}개</h2>
            <input type="search" id="${id("pf")}" placeholder="코드 · 이름 찾기" value="${esc(S.filter)}" aria-label="공통코드 찾기">
            <div class="plist" id="${id("plist")}"></div>
          </aside>
          <section class="gcard cv">
            <div class="stage">
              <svg id="${id("svg")}" viewBox="0 0 ${VB.w} ${VB.h}" role="application" aria-label="${esc(g.name)} 그래프 캔버스">
                <defs>
                  <pattern id="${id("dots")}" width="25" height="25" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1.1" style="fill:var(--grid)"/></pattern>
                  ${[["ok", "var(--accent)"], ["none", "var(--signal)"], ["ext", "var(--muted)"]].map(([k, col]) =>
                    `<marker id="${id("mk-" + k)}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" style="fill:${col}"/></marker>`).join("")}
                </defs>
                <rect x="0" y="0" width="${VB.w}" height="${VB.h}" fill="url(#${id("dots")})"/>
                <g id="${id("layer")}"></g><g id="${id("temp")}" pointer-events="none"></g>
              </svg>
              <div class="emptyhint" id="${id("emptyhint")}" hidden><span>① 왼쪽 공통코드에서 상태를 끌어다 놓고<br>② 상태 오른쪽 ● 을 끌어 다른 상태에 놓아 화살표를 만들고<br>③ 화살표를 눌러 업무에서 부르는 이름을 적으세요</span></div>
            </div>
          </section>
          <aside class="insp" id="${id("insp")}"></aside>
        </div>` : `
        <section class="gcard emptyst"><span class="st st-ext">공통코드 받기 전</span>
          <h2>${esc(g.name)} <span class="mono note">${esc(g.id)}</span></h2>
          <p class="note" style="max-width:62ch">${esc(g.hint)}</p></section>`}`;
      bindBar();
      if (S.creating) return bindCreate();
      if (!g.loaded) return;
      refresh(); bindCanvas();
    }

    /* 새 그래프 — 아직 그래프로 안 만든 공통코드 그룹을 골라 빈 캔버스를 연다 */
    const freeGroups = () => { const used = new Set(GRAPHS.filter(g => g.loaded).map(g => g.k.code_group.id)); return (D.codes || []).filter(c => !used.has(c.id)); };
    const nameOf = cg => cg.name.replace(/(구분)?코드$/, "") || cg.id;
    function createCard(){
      const free = freeGroups(), N = S.newG || (S.newG = { cg: free[0] ? free[0].id : "", dom: opts.domain || S.doms[0] || "pd", entity: "", name: free[0] ? nameOf(free[0]) : "" });
      const cg = free.find(x => x.id === N.cg), guess = cg ? guessField({ k: { graph: {}, code_group: cg } }) : null;
      if (!free.length) return `<section class="gcard emptyst"><span class="st st-ext">새 그래프</span><h2>그래프로 아직 안 만든 공통코드 그룹이 없습니다</h2>
        <p class="note" style="max-width:66ch">지금 받은 공통코드 그룹(${(D.codes || []).map(c => esc(c.id)).join(" · ") || "없음"})은 모두 그래프가 있습니다.
          공통코드 테이블 export(<span class="mono">data/codes/common_codes.csv</span>)에 그룹을 추가하고 화면 데이터를 다시 만들면 여기에 나타납니다 (<span class="mono">tap.cli ui-data</span>, 서버로 열었다면 새로고침).</p>
        <button class="gbtn" id="${id("ncCancel")}">돌아가기</button></section>`;
      return `<section class="gcard form" style="max-width:640px">
        <div class="row" style="justify-content:space-between"><h2>새 그래프</h2></div>
        <div class="fld"><label for="${id("ncg")}">공통코드 그룹 — 아직 그래프로 안 만든 것</label>
          <select id="${id("ncg")}">${free.map(c => `<option value="${esc(c.id)}" ${c.id === N.cg ? "selected" : ""}>${esc(c.id)} · ${esc(c.name)} · ${Object.keys(c.codes).length}개</option>`).join("")}</select>
          ${cg ? `<span class="hint">${(cg.order || Object.keys(cg.codes)).slice(0, 12).map(c => `${esc(c)} ${esc(cg.codes[c])}`).join(" · ")}${Object.keys(cg.codes).length > 12 ? " …" : ""}</span>` : ""}</div>
        <div class="two">
          <div class="fld"><label for="${id("nname")}">그래프 이름</label><input type="text" id="${id("nname")}" value="${esc(N.name)}"></div>
          <div class="fld"><label for="${id("nent")}">상태를 가진 대상</label><input type="text" id="${id("nent")}" value="${esc(N.entity)}" placeholder="예: 판매상품, 주문"></div>
        </div>
        <div class="fld"><label for="${id("ndom")}">담당 도메인 — 상태 코드 그룹의 주인</label>
          ${opts.domain ? `<input type="text" id="${id("ndom")}" value="${esc(DOMS[opts.domain] || opts.domain)} (${esc(opts.domain)})" readonly>`
            : `<select id="${id("ndom")}">${Object.entries(DOMS).map(([d, n]) => `<option value="${d}" ${d === N.dom ? "selected" : ""}>${n} (${d})</option>`).join("")}</select>`}</div>
        <div class="box"><b>조회 결과에서 상태를 읽는 필드 (자동 추정)</b>
          <p class="ev">${guess && guess.v ? `<span class="mono">${esc(guess.v)}</span> — ${esc(guess.why)}` : `못 찾았습니다 — ${esc(guess ? guess.why : "")}. 만든 뒤 '그래프 설정'에서 고르세요.`}</p></div>
        <div class="row"><button class="gbtn pri" id="${id("ncMake")}">만들기</button><button class="gbtn ghost" id="${id("ncCancel")}">취소</button></div>
      </section>`;
    }
    function bindCreate(){
      const N = S.newG || {};
      el("ncCancel").onclick = () => { S.creating = false; S.newG = null; render(); };
      if (!el("ncMake")) return;
      el("ncg").onchange = () => { const cg = freeGroups().find(x => x.id === el("ncg").value); N.cg = cg.id; N.name = nameOf(cg); N.entity = el("nent").value; render(); };
      el("nname").oninput = () => { N.name = el("nname").value; };
      el("nent").oninput = () => { N.entity = el("nent").value; };
      if (!opts.domain) el("ndom").onchange = () => { N.dom = el("ndom").value; };
      el("ncMake").onclick = () => {
        const cg = freeGroups().find(x => x.id === N.cg), name = (N.name || "").trim(), dom = opts.domain || N.dom;
        if (!cg) return toast("공통코드 그룹을 고르세요.");
        if (!name) return toast("그래프 이름을 적으세요.");
        const guess = guessField({ k: { graph: {}, code_group: cg } });
        const k = { graph: { id: cg.id, name, domain: dom, entity: (N.entity || "").trim() || name, state_field: guess.v, entry_states: [], verify_key_fields: [] },
          code_group: cg, transitions: [], lookups: [] };
        GRAPHS.push(fromK(k, { isNew: true }));
        if (!opts.domain && !S.doms.includes(dom)) S.doms = S.doms.concat([dom]);
        switchTo(cg.id); S.newG = null; render();
        toast(`${name} 그래프를 만들었습니다. 왼쪽 공통코드를 캔버스로 끌어다 놓으세요.${S.server ? "" : " 저장 전까지는 이 화면에만 있습니다."}`);
      };
    }
    function refresh(){ renderPalette(); renderLayer(); renderInspector(); renderCounts(); }
    function renderCounts(){
      const w = workEdges(), named = w.filter(e => e.name).length, noname = w.length - named;
      el("counts").innerHTML = `<span>상태 <b>${placed().length}</b>개 · 화살표 <b>${w.length}</b>개 (이름 확정 <b>${named}</b> ·
        <button class="need" id="${id("needB")}" ${noname ? "" : "disabled"} title="${noname ? "누르면 이름 없는 화살표로 차례로 이동" : ""}">이름 없음 ${noname}</button>)</span>
        ${S.saved ? `<span class="st st-good">승인본 v${S.saved.v}</span>` : ""}
        <div class="more"><button class="gbtn sm" id="${id("moreB")}" aria-haspopup="true" aria-expanded="${!!S.menu}">⋯ 더보기</button>
          ${S.menu ? `<div class="menu" role="menu">
            <button data-m="set">그래프 설정 (상태 필드)</button>
            ${(opts.actions || []).map((a, i) => `<button data-act="${i}">${esc(a.label())}</button>`).join("")}
            <hr><button data-m="reset">${graph().draft ? "저장본으로 되돌리기" : (graph().k.transitions || []).length ? "확인된 그래프로 되돌리기" : "캔버스 비우기"}</button></div>` : ""}</div>`;
      el("needB").onclick = () => { const list = w.filter(e => !e.name); if (!list.length) return;
        const cur = list.findIndex(e => S.sel.kind === "edge" && S.sel.id === key(e.from, e.to)), n = list[(cur + 1) % list.length];
        S.sel = { kind: "edge", id: key(n.from, n.to) }; renderLayer(); renderInspector(); };
      el("moreB").onclick = ev => { ev.stopPropagation(); S.menu = !S.menu; renderCounts(); };
      el("counts").querySelectorAll("[data-m]").forEach(b => b.onclick = () => { S.menu = false; renderCounts();
        ({ set: openSettings, reset: () => { const g = graph(); S = initial(S.graph); render();
          toast(g.draft ? "저장본으로 되돌렸습니다." : (g.k.transitions || []).length ? "확인된 그래프로 되돌렸습니다." : "캔버스를 비웠습니다."); } })[b.dataset.m](); });
      el("counts").querySelectorAll("[data-act]").forEach(b => b.onclick = () => { S.menu = false; renderCounts(); opts.actions[+b.dataset.act].onClick(); });
    }
    function bindBar(){
      el("gs").onchange = () => { switchTo(el("gs").value); render(); };
      root.querySelectorAll(".bar [data-act]").forEach(b => b.onclick = () => opts.actions[+b.dataset.act].onClick());
      el("newG").onclick = () => { S.creating = true; S.newG = null; render(); };
      root.querySelectorAll("[data-dom]").forEach(b => b.onclick = () => {
        const d = b.dataset.dom; S.doms = S.doms.includes(d) ? S.doms.filter(x => x !== d) : [...S.doms, d]; if (!S.doms.length) S.doms = [d]; render(); });
      if (el("testB")) el("testB").onclick = openTest;
      if (el("saveB")) el("saveB").onclick = openSave;
    }
    /* 팔레트 */
    function renderPalette(){
      const f = S.filter.trim();
      el("plist").innerHTML = CODES().filter(([c, n]) => !f || c.includes(f) || n.includes(f)).map(([c, n]) => {
        const on = !!S.nodes[c];
        return `<button class="pitem ${on ? "placed" : ""}" data-pal="${c}" title="${on ? "캔버스에 있음 — 누르면 선택" : "끌어다 놓거나 누르면 추가"}">
          <span class="mono">${c}</span><span>${esc(n)}</span>${on ? `<span class="note">배치됨</span>` : "<span></span>"}</button>`;
      }).join("") || `<p class="note">찾는 코드가 없습니다.</p>`;
      el("pf").oninput = () => { S.filter = el("pf").value; renderPalette(); };
      el("plist").querySelectorAll("[data-pal]").forEach(b => b.addEventListener("pointerdown", ev => palDown(ev, b.dataset.pal)));
    }
    function freeSpot(){
      for (const y of [150, 420, 285, 520, 60]) for (let x = 85; x <= 1010; x += 150)
        if (!Object.values(S.nodes).some(n => Math.abs(n.x - x) < 135 && Math.abs(n.y - y) < 70)) return { x, y };
      return { x: 550, y: 285 };
    }
    function addNode(c, p){
      S.nodes[c] = { x: clamp(p.x, NW / 2 + 6, VB.w - NW / 2 - 6), y: clamp(p.y, NH / 2 + 30, VB.h - NH / 2 - 10), role: "api" };
      S.sel = { kind: "node", id: c }; refresh();
    }
    let pal = null;
    function palDown(ev, c){
      if (S.nodes[c]){ S.sel = { kind: "node", id: c }; refresh(); return; }
      pal = { c, x: ev.clientX, y: ev.clientY, ghost: null };
      const move = e => {
        if (!pal) return;
        if (!pal.ghost && Math.hypot(e.clientX - pal.x, e.clientY - pal.y) > 5){
          pal.ghost = document.createElement("div"); pal.ghost.className = "ge-ghost"; pal.ghost.innerHTML = `<b>${c}</b>${esc(NAME(c))}`; document.body.appendChild(pal.ghost); }
        if (pal.ghost){ pal.ghost.style.left = e.clientX + "px"; pal.ghost.style.top = e.clientY + "px"; el("svg").classList.toggle("over", overSvg(e)); }
      };
      const up = e => {
        window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); window.removeEventListener("pointercancel", up);
        if (!pal) return;
        const dragged = !!pal.ghost; if (pal.ghost) pal.ghost.remove(); el("svg").classList.remove("over");
        if (dragged){ if (e.type === "pointerup" && overSvg(e)){ const p = toSvg(e); addNode(c, { x: snap(p.x), y: snap(p.y) }); toast(`${sn(c)} 을(를) 놓았습니다.`); } }
        else if (e.type === "pointerup"){ addNode(c, freeSpot()); toast(`${sn(c)} 을(를) 빈 자리에 놓았습니다. 끌어서 옮길 수 있어요.`); }
        pal = null;
      };
      window.addEventListener("pointermove", move); window.addEventListener("pointerup", up); window.addEventListener("pointercancel", up);
      ev.preventDefault();
    }
    function overSvg(e){ const r = el("svg").getBoundingClientRect(); return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom; }
    function toSvg(e){ const r = el("svg").getBoundingClientRect(); return { x: (e.clientX - r.left) * VB.w / r.width, y: (e.clientY - r.top) * VB.h / r.height }; }

    /* 캔버스 */
    function boundary(c, p, gap){ const dx = p.x - c.x, dy = p.y - c.y; if (!dx && !dy) return { x: c.x, y: c.y };
      const t = Math.min(dx ? (NW / 2 + gap) / Math.abs(dx) : Infinity, dy ? (NH / 2 + gap) / Math.abs(dy) : Infinity); return { x: c.x + dx * t, y: c.y + dy * t }; }
    function geom(e){
      const a = S.nodes[e.from], b = S.nodes[e.to], dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
      const both = !!edgeOf(key(e.to, e.from)), bend = both ? 34 : 0;
      const cp = { x: (a.x + b.x) / 2 + dy / len * bend, y: (a.y + b.y) / 2 - dx / len * bend };
      const s = boundary(a, both ? cp : b, 2), t = boundary(b, both ? cp : a, 7);
      return { d: `M${s.x},${s.y} Q${cp.x},${cp.y} ${t.x},${t.y}`, lx: (s.x + 2 * cp.x + t.x) / 4, ly: (s.y + 2 * cp.y + t.y) / 4 };
    }
    function renderLayer(){
      const sel = S.sel, en = entry();
      let edges = "", hits = "", nodes = "";
      for (const e of S.edges){
        if (!S.nodes[e.from] || !S.nodes[e.to]) continue;
        const g = geom(e), k = key(e.from, e.to), on = sel.kind === "edge" && sel.id === k;
        const [col, dash, mk] = isExternal(e) ? ["var(--muted)", "2 4", "ext"] : !e.name ? ["var(--signal)", "6 4", "none"] : ["var(--accent)", "", "ok"];
        const label = isExternal(e) ? "외부" : e.name || "이름 없음";
        edges += `<path d="${g.d}" fill="none" style="stroke:${col}" stroke-width="${on ? 3.4 : 1.9}" ${dash ? `stroke-dasharray="${dash}"` : ""} marker-end="url(#${id("mk-" + mk)})"/>
          <text x="${g.lx}" y="${g.ly + 4}" text-anchor="middle" font-size="12" font-weight="${on ? 700 : 500}" style="fill:${col};paint-order:stroke;stroke:var(--panel-2);stroke-width:5px;pointer-events:none">${esc(label)}</text>`;
        hits += `<path class="hit" data-edge="${k}" d="${g.d}" fill="none" stroke="transparent" stroke-width="18"><title>${esc(NAME(e.from))} → ${esc(NAME(e.to))} · 눌러서 편집</title></path>`;
      }
      for (const c of placed()){
        const n = S.nodes[c], on = sel.kind === "node" && sel.id === c, ext = n.role === "ext", ent = c === en;
        const x = n.x - NW / 2, y = n.y - NH / 2;
        nodes += `<g class="node" data-node="${c}" tabindex="0" role="button" aria-label="${esc(sn(c))}${ent ? " 진입 상태" : ""}">
          <rect x="${x}" y="${y}" width="${NW}" height="${NH}" rx="9" style="fill:${ent ? "var(--accent-soft)" : "var(--panel)"};stroke:${on ? "var(--ink)" : ext ? "var(--muted)" : "var(--accent)"}" stroke-width="${on ? 2.6 : ent ? 2.2 : 1.3}" ${ext ? 'stroke-dasharray="5 4"' : ""}/>
          <text x="${n.x}" y="${n.y - 4}" text-anchor="middle" font-size="14" font-weight="600" style="fill:${ext ? "var(--muted)" : "var(--ink)"};font-family:var(--mono)">${c}</text>
          <text x="${n.x}" y="${n.y + 14}" text-anchor="middle" font-size="12" style="fill:${ext ? "var(--muted)" : "var(--ink-2)"}">${esc(NAME(c))}</text>
          ${ent ? `<text x="${n.x}" y="${y - 7}" text-anchor="middle" font-size="11" font-weight="600" style="fill:var(--accent)">진입</text>` : ext ? `<text x="${n.x}" y="${y - 7}" text-anchor="middle" font-size="11" style="fill:var(--muted)">외부에서 생김</text>` : ""}
        </g>
        ${on ? `<g class="xbtn" data-del="${c}" role="button" aria-label="${esc(sn(c))} 캔버스에서 빼기"><title>캔버스에서 빼기 (Delete)</title>
          <circle cx="${x + NW}" cy="${y}" r="10" style="fill:var(--panel);stroke:var(--danger)" stroke-width="1.6"/>
          <path d="M${x + NW - 4},${y - 4} L${x + NW + 4},${y + 4} M${x + NW + 4},${y - 4} L${x + NW - 4},${y + 4}" style="stroke:var(--danger)" stroke-width="1.8" stroke-linecap="round"/></g>` : ""}
        <g class="port" data-port="${c}"><title>끌어서 화살표 만들기</title>
          <circle cx="${x + NW}" cy="${n.y}" r="13" fill="transparent"/>
          <circle class="ring" cx="${x + NW}" cy="${n.y}" r="6.5" style="fill:var(--panel);stroke:var(--accent)" stroke-width="2"/>
          <circle cx="${x + NW}" cy="${n.y}" r="2.6" style="fill:var(--accent)"/></g>`;
      }
      el("layer").innerHTML = edges + hits + nodes;
      el("emptyhint").hidden = Object.keys(S.nodes).length > 0;
    }
    let drag = null;
    function bindCanvas(){
      const svg = el("svg");
      svg.addEventListener("pointerdown", ev => {
        const del = ev.target.closest("[data-del]");
        if (del){ ev.preventDefault(); removeNode(del.dataset.del); return; }
        const port = ev.target.closest("[data-port]"), node = ev.target.closest("[data-node]"), edge = ev.target.closest("[data-edge]"), p = toSvg(ev);
        if (port){ drag = { type: "link", from: port.dataset.port }; svg.setPointerCapture(ev.pointerId); ev.preventDefault(); drawTemp(p); return; }
        if (node){ const c = node.dataset.node, n = S.nodes[c]; drag = { type: "move", id: c, dx: p.x - n.x, dy: p.y - n.y, sx: p.x, sy: p.y, moved: false };
          svg.setPointerCapture(ev.pointerId); ev.preventDefault(); return; }
        if (edge){ S.sel = { kind: "edge", id: edge.dataset.edge }; renderLayer(); renderInspector(); return; }
        if (S.sel.kind !== "none"){ S.sel = { kind: "none" }; renderLayer(); renderInspector(); }
      });
      svg.addEventListener("pointermove", ev => {
        if (!drag) return;
        const p = toSvg(ev);
        if (drag.type === "move"){
          if (!drag.moved && Math.hypot(p.x - drag.sx, p.y - drag.sy) < 4) return;
          drag.moved = true; const n = S.nodes[drag.id];
          n.x = clamp(p.x - drag.dx, NW / 2 + 6, VB.w - NW / 2 - 6); n.y = clamp(p.y - drag.dy, NH / 2 + 30, VB.h - NH / 2 - 10); renderLayer();
        } else drawTemp(p, ev);
      });
      const end = ev => {
        if (!drag) return;
        const d = drag; drag = null;
        if (d.type === "move"){ const n = S.nodes[d.id]; n.x = snap(n.x); n.y = snap(n.y); if (!d.moved) S.sel = { kind: "node", id: d.id }; renderLayer(); if (!d.moved) renderInspector(); }
        else { el("temp").innerHTML = ""; const t = ev.type === "pointerup" ? document.elementFromPoint(ev.clientX, ev.clientY)?.closest("[data-node],[data-port]") : null;
          const to = t ? (t.dataset.node || t.dataset.port) : null; if (to) addEdge(d.from, to); }
      };
      svg.addEventListener("pointerup", end); svg.addEventListener("pointercancel", end);
      svg.addEventListener("keydown", ev => { const node = ev.target.closest("[data-node]");
        if (node && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); S.sel = { kind: "node", id: node.dataset.node }; renderLayer(); renderInspector(); } });
    }
    function drawTemp(p, ev){
      const a = S.nodes[drag.from], s = { x: a.x + NW / 2, y: a.y };
      let hot = "";
      if (ev){ const t = document.elementFromPoint(ev.clientX, ev.clientY)?.closest("[data-node]");
        if (t && t.dataset.node !== drag.from){ const n = S.nodes[t.dataset.node]; hot = `<rect x="${n.x - NW / 2 - 4}" y="${n.y - NH / 2 - 4}" width="${NW + 8}" height="${NH + 8}" rx="11" fill="none" style="stroke:var(--accent)" stroke-width="2" stroke-dasharray="4 3"/>`; } }
      el("temp").innerHTML = `${hot}<path d="M${s.x},${s.y} L${p.x},${p.y}" style="stroke:var(--accent)" stroke-width="2" stroke-dasharray="5 4" fill="none" marker-end="url(#${id("mk-ok")})"/>`;
    }
    function addEdge(a, b){
      if (a === b) return;
      if (edgeOf(key(a, b))){ S.sel = { kind: "edge", id: key(a, b) }; refresh(); return toast("이미 있는 화살표라 그 화살표를 열었습니다."); }
      S.edges.push({ from: a, to: b, name: "", st: "확정", origin: "사람" }); S.sel = { kind: "edge", id: key(a, b) }; refresh();
      toast(S.nodes[a].role === "ext" ? "외부에서 생기는 상태에서 나온 화살표라 API 가 필요 없습니다."
        : `${NAME(a)} → ${NAME(b)} 화살표를 만들었습니다. 업무에서 부르는 이름을 적으세요.`);
    }

    /* 속성 패널 */
    const pill = e => !e.name ? `<span class="st st-none">이름 없음</span>` : `<span class="st st-ok">확정</span>`;
    function renderInspector(){
      const s = S.sel;
      if (s.kind === "edge" && edgeOf(s.id)) return inspEdge(edgeOf(s.id));
      // 상태를 고르면 캔버스에 선택 표시와 × 만 — 오른쪽은 할 일 · 그래프 설정 그대로
      return inspNone();
    }
    function inspNone(){
      const iss = issues(), order = { err: 0, warn: 1, info: 2 }, mark = { err: `<span class="st st-err">필수</span>`, warn: `<span class="st st-none">확인</span>`, info: `<span class="st st-ext">참고</span>` };
      iss.sort((a, b) => order[a.lv] - order[b.lv]);
      const shown = S.allTodo ? iss : iss.slice(0, 3);
      el("insp").innerHTML = `<section class="gcard form">
          <div class="row" style="justify-content:space-between"><h2>다음 할 일</h2><span class="note">${iss.filter(x => x.lv !== "info").length}개 남음</span></div>
          <div class="todo">${shown.map((x, i) => `<button data-todo="${i}">${mark[x.lv]}<span>${esc(x.msg)}</span></button>`).join("") || `<p class="note">남은 일이 없습니다. 위의 <b>저장</b>을 누르세요.</p>`}</div>
          ${iss.length > 3 ? `<button class="gbtn sm ghost" id="${id("allT")}">${S.allTodo ? "접기" : `전체 보기 (${iss.length})`}</button>` : ""}
          <p class="note">화살표를 누르면 여기서 이름을 적습니다. 상태는 끌어서 옮기고, 눌러서 나오는 × 로 뺍니다.</p>
        </section>`;
      el("insp").querySelectorAll("[data-todo]").forEach(b => b.onclick = () => { const x = shown[+b.dataset.todo];
        if (x.open === "set") return openSettings();
        if (x.sel) S.sel = x.sel; renderLayer(); renderInspector(); });
      if (el("allT")) el("allT").onclick = () => { S.allTodo = !S.allTodo; renderInspector(); };
    }
    function inspEdge(e){
      if (isExternal(e)){
        el("insp").innerHTML = `<section class="gcard form"><div class="row" style="justify-content:space-between"><h2>${esc(NAME(e.from))} → ${esc(NAME(e.to))}</h2><span class="st st-ext">외부</span></div>
          <p class="note">출발 상태 ${esc(sn(e.from))} 이(가) '외부에서 생기는 상태'라서 이 변화는 고객 주문 · 결제처럼 우리 밖에서 일어납니다. API 가 필요 없습니다.</p>
          <div class="row"><button class="gbtn sm dng" id="${id("delE")}">화살표 지우기</button><button class="gbtn sm ghost" id="${id("closeI")}">닫기</button></div></section>`;
        el("delE").onclick = () => { S.edges = S.edges.filter(x => x !== e); S.sel = { kind: "none" }; refresh(); };
        el("closeI").onclick = () => { S.sel = { kind: "none" }; refresh(); };
        return;
      }
      const rev = edgeOf(key(e.to, e.from));
      el("insp").innerHTML = `<section class="gcard form">
        <div class="row" style="justify-content:space-between"><h2>${esc(NAME(e.from))} → ${esc(NAME(e.to))}</h2>${pill(e)}</div>
        <div class="fld">
          <div class="two"><input type="text" id="${id("fn")}" value="${esc(e.name)}" placeholder="업무에서 부르는 이름 · 예: 출고완료취소" aria-label="업무에서 부르는 이름"><button class="gbtn pri" id="${id("okE")}">${e.name ? "이름 바꾸기" : "확정"}</button></div>
          <span class="hint">화면 · 업무에서 쓰는 말 그대로 적어 주세요.</span></div>
        ${!rev ? `<div class="box"><p class="ev">되돌리는 화살표(${esc(NAME(e.to))} → ${esc(NAME(e.from))})가 없습니다. 실행 중 실패하면 이 단계는 되돌릴 수 없어요. 필요하면 캔버스에서 ${esc(NAME(e.to))} 의 ● 을 끌어 ${esc(NAME(e.from))} 에 놓으세요.</p></div>` : ""}
        <div class="row"><button class="gbtn sm dng" id="${id("delE")}">화살표 지우기</button><button class="gbtn sm ghost" id="${id("closeI")}">닫기</button></div>
      </section>`;
      const fn = el("fn");
      fn.onkeydown = ev => { if (ev.key === "Enter"){ ev.preventDefault(); el("okE").click(); } };
      el("okE").onclick = () => {
        const v = fn.value.trim(); if (!v) return toast("업무에서 부르는 이름을 적으세요.");
        e.origin = "사람"; e.name = v; e.st = "확정";
        next(); toast(`'${v}' 로 확정했습니다.`);
      };
      el("delE").onclick = () => { S.edges = S.edges.filter(x => x !== e); S.sel = { kind: "none" }; refresh(); toast("화살표를 지웠습니다."); };
      el("closeI").onclick = () => { S.sel = { kind: "none" }; refresh(); };
    }
    function next(){ const n = workEdges().find(x => !x.name); S.sel = n ? { kind: "edge", id: key(n.from, n.to) } : { kind: "none" }; refresh(); if (S.drawM) S.drawM(el("mb")); }
    function removeNode(c){
      const k = S.edges.filter(e => e.from === c || e.to === c).length; delete S.nodes[c]; S.edges = S.edges.filter(e => e.from !== c && e.to !== c);
      S.sel = { kind: "none" }; refresh(); toast(`${sn(c)} 을(를) 캔버스에서 뺐습니다${k ? ` (화살표 ${k}개 함께)` : ""}.`);
    }
    function removeEdge(k){ const e = edgeOf(k); if (!e) return; S.edges = S.edges.filter(x => x !== e); S.sel = { kind: "none" }; refresh(); toast(`${NAME(e.from)} → ${NAME(e.to)} 화살표를 지웠습니다.`); }

    /* 시험 · 검수 · 저장 */
    function yaml(){
      const g = graph(), q = s => JSON.stringify(String(s)), en = entry();
      const ts = workEdges().filter(e => e.name), skip = workEdges().length - ts.length;
      return [
        `# ${g.name} 그래프 — 화면에서 저장 (${S.saved ? `승인본 v${S.saved.v}` : "저장 전 미리보기"}). 노드 흐름만: 상태 · 화살표 · 업무 이름 (이름 없는 화살표 ${skip}개는 빠짐)`,
        `# API 와 '조회로 찾을 수 있는 상태'는 저장하지 않는다 — 시나리오를 만들 때 ② 경로 탐색 · ③ API 선택이 정한다. 사람이 고정한 API · 조회 방법은 서버가 합칠 때 유지된다`,
        `version: ${S.saved ? S.saved.v : 0}`, `graph:`, `  id: ${g.id}`, `  name: ${q(g.name)}`, `  domain: ${g.dom}`, `  entity: ${q(g.k.graph.entity)}`,
        `  state_field: ${S.stateField.st === "확정" ? S.stateField.v : "null   # 확정 전이라 빠짐"}`, `  entry_states: []   # 정하지 않음 — 찾을 수 있는 상태 중 가장 앞 단계에서 출발`,
        `  verify_key_fields: [${(g.k.graph.verify_key_fields || []).join(", ")}]`,
        `code_group:`, `  id: ${g.k.code_group.id}`, `  name: ${q(g.k.code_group.name)}`, `  codes:   # 공통코드 전부 — 캔버스에 없는 상태를 고른 요청은 이유와 함께 거절된다`, ...CODES().map(([c, n]) => `    ${q(c)}: ${q(n)}`),
        `transitions:`, ...(ts.length ? ts.flatMap(e => [`  - name: ${q(e.name)}`, `    from: ${q(e.from)}`, `    to: ${q(e.to)}`]) : [`  []`]),
        `layout:   # 화면 배치`, ...placed().map(c => `  ${q(c)}: [${S.nodes[c].x}, ${S.nodes[c].y}]`),
      ].join("\n");
    }
    function openM(title, draw){
      closeM();
      const ov = document.createElement("div"); ov.className = "ge ge-ov"; ov.id = id("ov");
      ov.innerHTML = `<div class="ge-box" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="ge-mh"><h2>${esc(title)}</h2><button class="gbtn sm ghost" data-x>닫기</button></div><div id="${id("mb")}"></div></div>`;
      ov.addEventListener("click", ev => { if (ev.target === ov || ev.target.closest("[data-x]")) closeM(); });
      ov.addEventListener("keydown", ev => { if (ev.key === "Escape") closeM(); });
      document.body.appendChild(ov); S.drawM = draw; draw(el("mb")); const f = ov.querySelector("select,input,button.pri"); if (f) f.focus();
    }
    function closeM(){ const ov = el("ov"); if (ov) ov.remove(); S.drawM = null; }
    function openTest(){
      openM("시험해 보기", box => {
        const T = S.test; if (!T.target || !S.nodes[T.target]) T.target = placed()[placed().length - 1] || ""; if (!T.from || !S.nodes[T.from]) T.from = placed()[0] || "";
        const p = T.target && T.from ? search(T.from, T.target, T.must || null) : null;
        const o2 = (sel, none) => (none ? `<option value="">(없음)</option>` : "") + placed().map(c => `<option value="${c}" ${c === sel ? "selected" : ""}>${esc(sn(c))}</option>`).join("");
        box.innerHTML = `<div class="form">
          <div class="two"><div class="fld"><label for="${id("tf")}">출발 상태</label><select id="${id("tf")}">${o2(T.from)}</select></div>
            <div class="fld"><label for="${id("tt")}">목표 상태</label><select id="${id("tt")}">${o2(T.target)}</select></div></div>
          <div class="fld"><label for="${id("tm")}">그 전에 거쳐야 할 상태</label><select id="${id("tm")}">${o2(T.must, true)}</select></div>
          <div class="box path">${!T.target ? `<span class="note">상태를 먼저 캔버스에 놓으세요.</span>` : p ? `<div><span class="st st-ok">경로</span><br>${esc(sn(T.from))}${p.map(e => ` → ${esc(e.name)} → ${esc(sn(e.to))}`).join("")} <span class="note">· 화살표 ${p.length}개</span></div>`
            : `<div><span class="st st-err">경로 없음</span><br><span style="font-family:var(--sans)">${esc(sn(T.from))} 에서 ${esc(sn(T.target))}(으)로 가는 화살표 길이 없습니다 (이름 없는 화살표는 빼고 계산).</span></div>`}</div></div>`;
        el("tf").onchange = () => { T.from = el("tf").value; S.drawM(box); };
        el("tt").onchange = () => { T.target = el("tt").value; S.drawM(box); };
        el("tm").onchange = () => { T.must = el("tm").value; S.drawM(box); };
      });
    }
    function openSave(){
      openM("저장", box => {
        const iss = issues(), err = iss.filter(x => x.lv === "err"), w = workEdges(), conf = w.filter(e => e.name).length;
        box.innerHTML = `<div class="form">
          <ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.8">
            <li>저장되는 화살표 <b>${conf}</b>개 (이름을 적은 것)</li>
            ${w.length - conf ? `<li>저장 안 되는 화살표 ${w.length - conf}개 (이름 없음)</li>` : ""}
            <li>상태 필드 ${S.stateField.st === "확정" ? `<span class="mono">${esc(S.stateField.v)}</span>` : "확정 전 — 빠짐"}</li>
          </ul>
          ${err.length ? `<div class="box warn"><b>먼저 끝내야 할 것 ${err.length}개</b>${err.map(x => `<p class="ev">${esc(x.msg)}</p>`).join("")}</div>` : ""}
          ${S.server ? "" : `<p class="note">로컬 서버(tap.cli serve)로 열어야 파일에 저장됩니다.</p>`}
          <details><summary style="font-size:12.5px;font-weight:500">저장될 내용 보기</summary><pre class="yaml">${esc(yaml())}</pre></details>
          <div class="row"><button class="gbtn pri" id="${id("save")}" ${err.length ? "disabled" : ""}>확인 후 저장</button><button class="gbtn ghost" data-x>취소</button></div></div>`;
        el("save").onclick = async () => {
          S.saved = { v: (S.saved ? S.saved.v : 0) + 1 }; let where = "";
          if (S.server){ try { const r = await fetch("/api/graph/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ graph_id: S.graph, yaml: yaml() }) });
            const j = await r.json(); where = j.file ? ` · ${j.file}` : ` · 저장 실패: ${j.error}`; } catch (e){ where = " · 서버에 저장하지 못했습니다"; } }
          closeM(); refresh(); toast(`승인본 v${S.saved.v} 로 저장했습니다${where}`);
        };
      });
    }
    function openSettings(){
      openM("그래프 설정", box => {
        const m = new Map(); if (S.stateField.v) m.set(S.stateField.v, []);
        D.ops.filter(o => o.kind === "read" && scopeDoms().includes(o.dom)).forEach(o => o.res.filter(r => /Gbcd$/.test(r[0])).forEach(r => { if (!m.has(r[0])) m.set(r[0], []); m.get(r[0]).push(o.sum); }));
        box.innerHTML = `<div class="form"><div class="fld"><label for="${id("sf")}">조회 결과에서 현재 상태를 읽는 필드</label>
          <select id="${id("sf")}">${[...m].map(([f, l]) => `<option value="${f}" ${f === S.stateField.v ? "selected" : ""}>${f} · ${esc(l.slice(0, 2).join(", "))}</option>`).join("")}</select>
          <span class="hint">자동으로 추정한 값입니다.</span></div>
          <div class="row">${S.stateField.st === "확정" ? `<span class="st st-ok">확정</span>` : `<button class="gbtn pri" id="${id("sfOk")}">확정</button>`}<button class="gbtn ghost" data-x>닫기</button></div></div>`;
        el("sf").onchange = () => { S.stateField = { v: el("sf").value, st: "추정" }; refresh(); S.drawM(box); };
        if (el("sfOk")) el("sfOk").onclick = () => { S.stateField.st = "확정"; refresh(); S.drawM(box); toast("상태 필드를 확정했습니다."); };
      });
    }
    let tt = null;
    function toast(msg){
      if (opts.toast) return opts.toast(msg);
      let t = document.getElementById("ge-toast"); if (!t){ t = document.createElement("p"); t.id = "ge-toast"; t.className = "ge-toast"; document.body.appendChild(t); }
      t.textContent = msg; t.hidden = false; clearTimeout(tt); tt = setTimeout(() => { t.hidden = true; }, 2800);
    }
    root.addEventListener("keydown", ev => {
      if (drag || S.sel.kind === "none" || /INPUT|SELECT|TEXTAREA/.test(ev.target.tagName)) return;
      if (ev.key === "Escape"){ S.sel = { kind: "none" }; refresh(); }
      else if (ev.key === "Delete" || ev.key === "Backspace"){ ev.preventDefault(); if (S.sel.kind === "node") removeNode(S.sel.id); else if (S.sel.kind === "edge") removeEdge(S.sel.id); }
    });
    if (location.protocol.startsWith("http")) fetch("/api/health").then(r => r.ok ? r.json() : null).then(j => { if (j && j.ok){ S0.server = S.server = true; } }).catch(() => {});
    document.addEventListener("click", ev => { if (S.menu && !ev.target.closest(".more")){ S.menu = false; if (el("counts")) renderCounts(); } });
    render();
    return { refresh(){ render(); }, setDomain(d){ opts.domain = d; const g = GRAPHS.find(x => x.dom === d); switchTo(g ? g.id : S.graph); render(); } };
  }

  /* 개발 담당자 검수 목록 (관리자 › 전사) — 저장된 그래프 기준. 화면에서 아직 저장 안 한 그래프는 저장한 뒤 나타난다 */
  function reviewItems(D, doms){
    doms = doms || ["pd", "od", "ds"];
    const all = (D.graphs || []).concat((D.drafts || []).filter(d => d && d.graph && !(D.graphs || []).some(g => g.graph.id === d.graph.id)));
    const out = [];
    all.forEach(g => { const codes = (D.codes || []).find(c => c.id === g.code_group.id) || g.code_group, nm = c => codes.codes[c] || c, f = g.graph.state_field;
      (g.transitions || []).filter(t => t.name).forEach(t => { const cs = matchEdge(D, t.name, nm(String(t.to)), doms, f, String(t.to)), st = statusOf(cs);
        if (st !== "찾음") out.push({ graph: g.graph.name, gid: g.graph.id, kind: "화살표", item: `${t.name} (${nm(String(t.from))} → ${nm(String(t.to))})`, status: st,
          why: cs[0] ? cs[0].why.join(" · ") : "후보 없음 — 명세 summary · 별칭 · 구분값 어디에도 비슷한 이름이 없음" }); });
      const states = [...new Set((g.transitions || []).flatMap(t => [String(t.from), String(t.to)]).concat(Object.keys(g.layout || {})))];
      states.forEach(c => { const cs = matchLookup(D, nm(c), c, f, doms), st = statusOf(cs);
        if (st === "확인 필요") out.push({ graph: g.graph.name, gid: g.graph.id, kind: "조회", item: `${c} ${nm(c)}`, status: st, why: cs[0].why.join(" · ") }); });
    });
    return out;
  }

  window.GraphEditor = { mount, matchEdge, matchLookup, statusOf, sim, reviewItems };
})();
