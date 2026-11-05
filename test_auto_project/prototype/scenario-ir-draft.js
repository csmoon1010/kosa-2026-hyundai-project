/* IR drafts are separate from executable scenarios. */
(function () {
  'use strict';
  const host = document.getElementById('scenarioIRDraft');
  if (!host) return;
  const labels = {max_turns:'최대 모델 호출 횟수',max_tokens:'최대 누적 토큰',max_seconds:'최대 생성 시간(초)',max_output_tokens:'호출당 최대 출력 토큰'};
  let defaults = {}, busy = false, loadedBudget=null, budgetRequest=0;
  let activeMode='basic';
  const emptyOptions=()=>({stop_retry:false,kb_rag:false,dependency_projection:false});
  let defaultOptions=emptyOptions(),activeOptions=emptyOptions();
  const optionLabels={stop_retry:'중지조건·재시도',kb_rag:'압축 1 · 조건별 ParameterKB 검색',dependency_projection:'압축 2 · 의존성 기반 STEP 문맥 선별'};   /* IR 입력 검토(approval_gate)는 화면에서 뺐다 (2026-11-05) — 실행 단계가 없어 아직 의미가 없음. 백엔드는 남겨 둠 */
  const stepEntries=new Map();
  let selectedStepId=null,xmlView='after';
  host.innerHTML = `
    <div class="card-hd"><h2>IR 초안 생성 · 결과</h2></div><div data-settings></div>
    <fieldset data-options><legend>생성 옵션 · 함께 선택 가능</legend>
      ${Object.entries(optionLabels).map(([key,label])=>`<label style="display:inline-block;margin:8px"><input type="checkbox" data-option-${key}> ${label}</label>`).join('')}
    </fieldset>
    <p class="note" data-mode-status>기본 모드 · 현재 매핑 후보 분석 흐름을 사용합니다.</p>
    <button type="button" class="btn" data-reset>옵션 기본값 복원</button>
    <p><label>저장된 승인본 <select data-files></select></label></p><button type="button" class="btn btn-primary" data-generate>IR 다시 생성</button>
    <p data-status role="status"></p><p data-log-file></p>
    <section class="ir-step-section" aria-label="시나리오 STEP">
      <h3>시나리오 STEP</h3><p data-step-empty class="note">승인본으로 생성하면 STEP을 표시합니다.</p>
      <div class="ir-step-layout"><nav data-step-list class="ir-step-list" aria-label="시나리오 단계 선택"></nav>
        <section data-step-detail class="ir-step-detail" aria-live="polite" hidden>
          <div class="ir-step-heading"><h3 data-step-title></h3><span class="ir-step-state" data-step-state></span></div>
          <div class="ir-step-context"><div data-step-task class="ir-step-kicker"></div><span class="ir-step-kicker">업무 조건</span><p data-step-condition></p></div>
          <div data-step-api class="ir-step-api"></div><div data-step-parameters></div>
          <div class="ir-step-heading"><h3>Baseline XML</h3><span data-step-xml-source class="note"></span></div>
          <div class="ir-log-tabs" role="tablist" aria-label="Baseline XML 보기">
            <button type="button" id="irDraftXMLAfter" role="tab" aria-controls="irDraftXMLPanel" aria-selected="true" data-xml-after>적용 후 미리보기</button>
            <button type="button" id="irDraftXMLBefore" role="tab" aria-controls="irDraftXMLPanel" aria-selected="false" data-xml-before>원본 Baseline</button>
          </div>
          <div id="irDraftXMLPanel" data-step-xml-panel role="tabpanel" aria-labelledby="irDraftXMLAfter"><pre><code data-step-xml-code></code></pre></div>
          <p class="note" data-step-xml-note></p>
        </section>
      </div>
    </section>
    <div data-progress aria-live="polite"></div><h3>생성 과정 · 턴 / 도구 호출</h3><div data-log class="ir-log-wrap"></div>
    <section class="ir-log-detail" aria-label="선택한 로그 상세"><h3 data-detail-title aria-live="polite">로그 행을 선택하세요</h3>
      <div class="ir-log-tabs" role="tablist" aria-label="요청 및 응답">
        <button type="button" role="tab" id="irDraftRequestTab" data-detail-request aria-controls="irDraftDetailPanel" aria-selected="false">요청 프롬프트 / 인자</button>
        <button type="button" role="tab" id="irDraftResponseTab" data-detail-response aria-controls="irDraftDetailPanel" aria-selected="true">응답 결과</button>
      </div><div id="irDraftDetailPanel" data-detail-panel role="tabpanel" aria-labelledby="irDraftResponseTab"><p class="note" data-detail-meta></p><pre><code data-detail-json></code></pre></div>
    </section><div data-result></div>
    <section aria-label="입력 결정 검토" hidden><h3>IR 입력 검토 · 입력 결정</h3>
      <p><label>저장된 검토 초안 <select data-reviews></select></label>
      <button type="button" class="btn" data-review-load>검토 불러오기</button></p>
      <p role="status" data-review-status>IR 입력 검토를 선택해 생성한 초안의 미해결 입력을 지금 입력 · 실행 시 입력으로 정하고 확정합니다.</p>
      <div data-review-content></div>
    </section>
    <section class="ir-run-history" aria-label="누적 IR 실행 로그">
      <h3>누적 IR 실행 기록</h3>
      <div class="ir-run-filters" aria-label="실행 기록 필터">
        <label>시작일 <input type="date" data-filter-from></label>
        <label>종료일 <input type="date" data-filter-to></label>
        <fieldset class="ir-run-option-filters"><legend>생성 옵션</legend>
          <label class="ir-run-filter-enable"><input type="checkbox" data-filter-options> 선택한 조합만 표시</label>
          <div>${Object.entries(optionLabels).map(([key,label])=>`<label class="ir-run-option"><input type="checkbox" data-filter-${key}> ${label}</label>`).join('')}</div>
        </fieldset>
        <button type="button" class="btn" data-filter-reset>필터 초기화</button>
      </div>
      <p class="note" data-runs-status>저장된 JSONL 실행 로그를 불러오는 중입니다.</p>
      <div data-runs-table class="ir-run-history-table"></div>
    </section>`;
  const get = key => host.querySelector('[data-'+key+']');
  function readOptions(){return Object.fromEntries(Object.keys(optionLabels).map(key=>[key,Boolean(get('option-'+key).checked)]));}
  function syncOptionDependencies(){}   /* 인젝션 대응 옵션을 빼서(2026-11-05) 옵션 사이 의존이 없다 */
  function writeOptions(options){for(const key of Object.keys(optionLabels))get('option-'+key).checked=Boolean(options[key]);syncOptionDependencies();}
  function lockOptions(value){for(const key of Object.keys(optionLabels))get('option-'+key).disabled=value;syncOptionDependencies();}
  function describeOptions(options){return Object.entries(optionLabels).filter(([key])=>options[key]).map(([,label])=>label).join(' + ')||'기본 모드';}
  function resultOptions(generation){return generation?.options||{...emptyOptions(),stop_retry:generation?.execution_mode==='validated'};}
  function showLogFile(data) {
    if(!data?.log_file)return;
    const area=get('log-file');area.replaceChildren();
    const label=document.createElement('span');label.textContent='전체 로그: '+data.log_file+' ';area.append(label);
    if(data.log_url?.startsWith('/api/scenario-ir-logs/')){
      const link=document.createElement('a');link.href=data.log_url;link.download='';link.textContent='JSONL 다운로드';area.append(link);
    }
  }
  function formatDuration(value){const seconds=Math.max(0,Math.floor(Number(value)||0));return Math.floor(seconds/60)+'분 '+String(seconds%60).padStart(2,'0')+'초';}
  let savedRunSummaries=[];
  function filteredRunSummaries(){
    const from=get('filter-from').value,to=get('filter-to').value;
    return savedRunSummaries.filter(run=>{
      const date=typeof run.started_at==='string'?run.started_at.slice(0,10):'';
      if(from&&(!date||date<from))return false;
      if(to&&(!date||date>to))return false;
      if(get('filter-options').checked&&(!run.options||Object.keys(optionLabels).some(key=>
        Boolean(run.options[key])!==Boolean(get('filter-'+key).checked))))return false;
      return true;
    });
  }
  function renderRunSummaries(runs,total=savedRunSummaries.length){
    const target=get('runs-table');
    if(!runs.length){target.replaceChildren();get('runs-status').textContent=total?'필터 조건에 맞는 실행 로그가 없습니다. (0 / '+total+')':'저장된 실행 로그가 없습니다.';return;}
    const table=document.createElement('table');table.className='ir-log-table ir-run-table';
    const head=document.createElement('thead'),headRow=document.createElement('tr');
    ['실행 시각','생성 옵션','상태','수행 시간','LLM 호출','턴','입력 토큰','출력 토큰','임베딩 토큰','총 토큰','STEP 수','STEP 최대 호출','임베딩 호출','예비 사용','중단 사유','로그'].forEach(label=>{const th=document.createElement('th');th.textContent=label;headRow.append(th);});
    head.append(headRow);table.append(head);
    const body=document.createElement('tbody');
    for(const run of runs){
      const row=document.createElement('tr');
      const b=run.budget,bu=run.budget_usage||{},l=b?.limits||{};
      const ratio=(value,limit)=>String(value??0)+' / '+(limit??'—');
      const values=[run.started_at?new Date(run.started_at).toLocaleString('ko-KR'):'—',
        run.options?describeOptions(run.options):'기록 없음',run.status||'미완료',ratio(run.duration_seconds,l.seconds)+'초',
        ratio(run.model_calls,l.llm_calls),run.turns??0,run.input_tokens??0,run.output_tokens??0,
        run.embedding_tokens??0,ratio(run.total_tokens,l.tokens),run.step_count??'—',
        bu.steps?Math.max(0,...Object.values(bu.steps))+' (기본 5)':'—',run.embedding_calls??'—',
        b?.version==='step_budget_v1'?'호출 '+(bu.reserve_calls||0)+'/2 · 토큰 '+(bu.token_reserve_used||0)+'/'+Math.min(30000,Math.max(0,l.tokens-b.step_count*50000))+' · 시간 '+Number(bu.time_reserve_used||0).toFixed(1)+'/'+Math.min(30,Math.max(0,l.seconds-b.step_count*60))+'초':'—',run.budget_reason||'—'];
      for(const value of values){const cell=document.createElement('td');cell.textContent=String(value);row.append(cell);}
      const linkCell=document.createElement('td');
      if(typeof run.filename==='string'&&/^IRRUN-[A-Za-z0-9-]+\.jsonl$/.test(run.filename)){
        const link=document.createElement('a');link.href='/api/scenario-ir-logs/'+encodeURIComponent(run.filename);link.download=run.filename;link.textContent='JSONL';linkCell.append(link);
      }else linkCell.textContent='—';
      row.append(linkCell);body.append(row);
    }
    table.append(body);const wrap=document.createElement('div');wrap.className='ir-log-wrap';wrap.append(table);target.replaceChildren(wrap);
    get('runs-status').textContent='JSONL 로그 '+runs.length+' / '+total+'개 · 최신 실행부터 표시';
  }
  function applyRunFilters(){renderRunSummaries(filteredRunSummaries());}
  async function loadRunSummaries(){
    const response=await fetch('/api/scenario-ir-log-summaries',{cache:'no-store'});
    if(!response.ok)throw new Error('저장된 IR 로그 요약을 불러오지 못했습니다.');
    const data=await response.json();savedRunSummaries=data.runs||[];applyRunFilters();
  }
  function status(message) { get('status').textContent = message; }
  const eventNames = {generation_start:'생성 시작',llm_request:'LLM 요청 · 프롬프트',llm_response:'LLM 출력 · 도구 선택 응답',tool_selected:'도구 결정',tool_start:'도구 호출 시작',tool_result:'도구 호출 결과',validation_feedback:'매핑 수정 안내',step_complete:'단계 완료',llm_error:'LLM 오류',generation_error:'생성 실패',generation_complete:'저장 완료'};
  let lastEvent = {}, started = 0;
  function progress() {
    const u=lastEvent.usage||{}, seconds=started ? ((performance.now()-started)/1000).toFixed(1) : '0.0';
    const turn=lastEvent.next_turn||lastEvent.turn||0;
    for(const row of logRows.values()){if(row.seconds===undefined)row.cells[5].textContent=((performance.now()-row.started)/1000).toFixed(1)+'초 (진행 중)';}
    const bu=lastEvent.budget_usage,b=lastEvent.budget;
    if(bu&&b){get('progress').textContent='STEP '+(lastEvent.step_id||'준비')+' 호출 '+(bu.steps?.[lastEvent.step_id]||0)+' (기본 5) · 공통 예비 '+bu.reserve_calls+'/2 사용 · LLM '+bu.llm_calls+'/'+b.limits.llm_calls+' · 토큰 '+bu.total_tokens+'/'+b.limits.tokens+' · 시간 '+Number(bu.elapsed_seconds).toFixed(1)+'/'+b.limits.seconds+'초 · 임베딩 '+(u.embedding_calls||0)+'회';return;}
    get('progress').textContent='전체 '+turn+'턴 · 단계 '+(lastEvent.step_id||'준비')+' / '+(lastEvent.step_turn||0)+'턴 · 누적 토큰 '+(u.total_tokens||0)+' (입력 '+(u.input_tokens||0)+' / 출력 '+(u.output_tokens||0)+' / 임베딩 '+(u.embedding_tokens||0)+', '+(u.embedding_calls||0)+'회) · 경과 '+seconds+'초';
  }
  const logRows = new Map();
  let selectedLogKey = null, detailTab = 'response';
  function resetLog() {
    logRows.clear();
    selectedLogKey=null;
    renderSelection();
    const t=document.createElement('table'); t.className='ir-log-table';
    const head=document.createElement('thead'), tr=document.createElement('tr');
    ['전체 턴','STEP 내 턴','STEP','종류 / 도구','상태','소요시간','토큰 이번 / 누적','valid'].forEach(label=>{
      const th=document.createElement('th');th.textContent=label;tr.append(th);
    });
    head.append(tr); t.append(head);
    const body=document.createElement('tbody');t.append(body);
    get('log').replaceChildren(t);
    return body;
  }
  let logBody=resetLog();
  function beautify(value, code=get('detail-json')) {
    let shown=value;
    if(typeof value==='string'){try{shown=JSON.parse(value);}catch(_){}}
    const text=JSON.stringify(shown,null,2)??String(shown);
    code.replaceChildren();
    const pattern=/"(?:\\.|[^"\\])*"(?=\s*:)|"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b/g;
    let end=0;
    for(const match of text.matchAll(pattern)){
      code.append(document.createTextNode(text.slice(end,match.index)));
      const span=document.createElement('span');
      span.className=match[0][0]==='"'?(text.slice(match.index+match[0].length).trimStart().startsWith(':')?'ir-json-key':'ir-json-string'):'ir-json-literal';
      span.textContent=match[0];code.append(span);end=match.index+match[0].length;
    }
    code.append(document.createTextNode(text.slice(end)));
  }
  function renderSelection() {
    const row=logRows.get(selectedLogKey);
    get('detail-request').setAttribute('aria-selected',String(detailTab==='request'));
    get('detail-response').setAttribute('aria-selected',String(detailTab==='response'));
    get('detail-panel').setAttribute('aria-labelledby',detailTab==='request'?'irDraftRequestTab':'irDraftResponseTab');
    if(!row){
      get('detail-title').textContent='로그 행을 선택하세요';
      get('detail-meta').textContent='선택한 행의 요청과 응답을 이 영역에서 확인할 수 있습니다.';
      beautify({message:'아직 선택된 로그가 없습니다.'});return;
    }
    get('detail-title').textContent='선택한 로그 · '+(row.kind==='backend'?'백엔드':row.turn+'턴')+' · STEP '+row.step_id+' · '+(row.tool||'LLM');
    const value=detailTab==='request'?row.request:row.response;
    get('detail-meta').textContent=(detailTab==='request'?(row.kind==='backend'?'백엔드 처리 입력':row.tool?'도구 호출 인자':'LLM 프롬프트'):'응답 결과')+' · JSON · 2칸 들여쓰기 · '+row.state;
    beautify(value===undefined?{status:'waiting',message:detailTab==='response'?'응답을 기다리고 있습니다.':'요청 정보가 아직 없습니다.'}:value);
  }
  function selectRow(key) {
    selectedLogKey=key;
    for(const [rowKey,row] of logRows){
      const selected=rowKey===key;row.tr.dataset.selected=String(selected);
      row.button.setAttribute('aria-pressed',String(selected));
    }
    renderSelection();
  }
  for(const tab of ['request','response']){
    const button=get('detail-'+tab);
    button.addEventListener('click',()=>{detailTab=tab;renderSelection();});
    button.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();detailTab=event.key==='Home'?'request':event.key==='End'?'response':tab==='request'?'response':'request';
      get('detail-'+detailTab).focus();renderSelection();
    });
  }
  function renderRow(row) {
    const c=row.cells;
    [row.turn??'—',row.step_turn??'—',row.step_id||'—',null,row.state].forEach((x,i)=>{if(i!==3)c[i].textContent=String(x);});
    row.button.textContent=row.tool||'LLM';
    row.button.setAttribute('aria-label',row.turn+'턴 STEP '+row.step_id+' '+(row.tool||'LLM')+' 상세 보기');
    c[5].textContent=row.seconds!==undefined ? row.seconds.toFixed(3)+'초' : ((performance.now()-row.started)/1000).toFixed(1)+'초 (진행 중)';
    c[6].textContent=row.kind==='backend'?'—':(row.turn_usage?.total_tokens??'—')+' / '+(row.usage?.total_tokens??'—');
    c[7].textContent=typeof row.valid==='boolean'?String(row.valid):row.tool==='validate_mapping'?(typeof row.response?.valid==='boolean'?String(row.response.valid):'미판정'):'—';
    if(logRows.get(selectedLogKey)===row)renderSelection();
  }
  function logEvent(event) {
    showLogFile(event);
    if(event.budget)showBudget(event.budget);
    if(event.execution_mode){activeMode=event.execution_mode;activeOptions=event.options||{...activeOptions,stop_retry:activeMode==='validated'};get('mode-status').textContent='실행 옵션: '+describeOptions(activeOptions);}
    updateSteps(event);
    lastEvent={...lastEvent,...event};
    if(event.event!=='llm_request')delete lastEvent.next_turn;
    progress();
    const isTool=event.event.startsWith('tool_');
    const backendNames={kb_retrieval:'ParameterKB 검색 · 백엔드',context_projection:'STEP 문맥 선별 · 백엔드',backend_canonical:'Canonical · 백엔드',backend_baseline_compare:'Baseline 비교 · 백엔드',material_check:'필요 자료 확인 · 백엔드',backend_output_defined:'앞 STEP 출력 보완 · 백엔드',
      mapping_validation:'validate_mapping · 백엔드',final_ir_validation:'최종 IR 검증 · 백엔드',mapping_repair:'매핑 수정 요청 · 백엔드',recovery_stopped:'복구 중단 · 백엔드',
      llm_retry:'LLM 통신 재시도 · 백엔드',llm_attempt_start:'LLM 통신 시도 · 백엔드',llm_attempt_error:'LLM 통신 오류 · 백엔드',llm_attempt_complete:'LLM 통신 수신 · 백엔드'};
    const isBackend=Boolean(backendNames[event.event]);
    const isLLM=event.event.startsWith('llm_')||event.event==='validation_feedback'||event.event==='step_complete';
    if(!isTool&&!isLLM&&!isBackend)return;
    const turn=event.next_turn||event.turn;
    const isAttempt=['llm_attempt_start','llm_attempt_error','llm_attempt_complete'].includes(event.event);
    const key=isBackend?'backend:'+event.step_id+':'+(isAttempt?'llm_attempt':event.event)+':'+(event.request_id||event.turn||0)+':'+(event.attempt||event.step_turn||0):isTool?'tool:'+event.step_id+':'+(event.call_id||turn+':'+event.tool):'llm:'+turn;
    let row=logRows.get(key);
    if(!row){
      const tr=document.createElement('tr');
      const cells=Array.from({length:8},()=>document.createElement('td'));
      const button=document.createElement('button');button.type='button';button.className='ir-log-select';
      button.setAttribute('aria-label','선택한 로그 상세 보기');cells[3].append(button);
      tr.append(...cells);tr.addEventListener('click',()=>selectRow(key));logBody.append(tr);
      row={tr,button,cells,started:performance.now()};logRows.set(key,row);
    }
    Object.assign(row,{turn,step_turn:event.step_turn??row.step_turn,step_id:event.step_id||row.step_id,tool:event.tool||row.tool,usage:event.usage||row.usage});
    if(isBackend){row.kind='backend';row.tool=backendNames[event.event];row.turn='—';row.step_turn='—';row.request=event.request??(isAttempt?row.request:undefined);row.response=event.result;row.seconds=event.backend_seconds??0;row.state='완료';}
    if(isBackend){
      if(isAttempt){
        row.tool='LLM 통신 시도 '+event.attempt+' · 백엔드';
        row.request=event.request??row.request;
        if(event.event==='llm_attempt_start'){row.seconds=undefined;row.state='통신 중';}
      }
      if(['mapping_validation','final_ir_validation','mapping_repair','recovery_stopped','llm_retry','llm_attempt_start','llm_attempt_error','llm_attempt_complete'].includes(event.event)){
        row.turn=event.turn??'—';row.step_turn=event.step_turn??'—';
      }
      row.valid=typeof event.result?.valid==='boolean'?event.result.valid:undefined;
      if(event.result?.valid===false||event.event==='llm_attempt_error')row.state='검사 / 통신 오류';
      if(event.event==='llm_retry')row.state='대기 후 재시도';
      if(event.event==='mapping_repair')row.state='수정 요청';
      if(event.event==='recovery_stopped')row.state='중단';
    }
    if(event.event==='llm_request'){row.request=event.input?{model:event.model,instructions:event.instructions,input:event.input,tools:event.tools,tool_choice:event.tool_choice,text:event.text,store:event.store,include:event.include}:{model:event.model,messages:event.messages,tools:event.tools};row.state='LLM 응답 대기';}
    if(event.event==='llm_response'){row.response={output:event.output,...(event.response_status?{status:event.response_status}:{finish_reason:event.finish_reason})};row.state='응답 수신';row.seconds=event.llm_seconds??(performance.now()-row.started)/1000;row.turn_usage=event.turn_usage;}
    if(event.event==='llm_error'){row.response={error:event.error};row.state='실패';row.seconds=event.llm_seconds??(performance.now()-row.started)/1000;}
    if(event.event==='tool_selected'){row.request=event.arguments;row.state='선택됨';}
    if(event.event==='tool_start')row.state='호출 중';
    if(event.event==='tool_result'){row.response=event.result;row.seconds=event.tool_seconds??(performance.now()-row.started)/1000;row.state=event.result?.error?'호출 오류':event.result?.valid===false?'검증 실패':'완료';}
    if(event.event==='validation_feedback'){row.response={...row.response,feedback:event.result};row.state='매핑 수정 필요';}
    if(event.event==='step_complete')row.state='백엔드 채택';
    renderRow(row);
    if(selectedLogKey===null)selectRow(key);
  }
  async function receive(response) {
    if (!response.ok) {
      const data=await response.json();showLogFile(data);throw new Error(data.error||'IR 생성 HTTP '+response.status);
    }
    if (!(response.headers.get('Content-Type')||'').includes('application/x-ndjson')) return response.json();
    const reader=response.body.getReader(), decoder=new TextDecoder();
    let buffer='', result=null, failure=null;
    function line(text) {
      if(!text.trim())return;
      const event=JSON.parse(text);
      if(event.event==='generation_complete') {
        result=event.result;
        logEvent({event:event.event,file:result.file,usage:result.usage,log_file:result.log_file,log_url:result.log_url});
      } else {
        logEvent(event);
        if(event.event==='generation_error') failure=event.error;
      }
    }
    while(true){
      const chunk=await reader.read();
      buffer+=decoder.decode(chunk.value||new Uint8Array(),{stream:!chunk.done});
      let end;while((end=buffer.indexOf('\n'))>=0){line(buffer.slice(0,end));buffer=buffer.slice(end+1);}
      if(chunk.done)break;
    }
    line(buffer);
    if(failure)throw new Error(failure);
    if(!result)throw new Error('생성 연결이 완료 결과 없이 종료되었습니다. 진행 로그를 확인하세요.');
    return result;
  }
  function settings() {
    return Object.fromEntries(Object.keys(labels).map(k => {
      const n = Number(host.querySelector('[name="ir-'+k+'"]').value);
      if (!Number.isInteger(n) || n <= 0) throw new Error('생성 설정은 양의 정수여야 합니다.');
      return [k,n];
    }));
  }
  function reset() { writeOptions(defaultOptions); }
  function showBudget(budget) {
    loadedBudget=budget;
    const l=budget.limits;
    get('settings').textContent='STEP '+budget.step_count+'개 · LLM '+l.llm_calls+'회 · 토큰 '+l.tokens.toLocaleString()+' · 시간 '+l.seconds+'초 · 호출당 출력 4,096 · STEP 기본 5회 + 공유 예비 2회 · 절대 상한 40회 / 400,000토큰 / 600초 (수정 불가)';
  }
  async function loadBudget() {
    const request=++budgetRequest, filename=get('files').value;
    loadedBudget=null;get('settings').textContent=filename?'예산 산정 중…':'STEP 문서 로드 필요';
    get('generate').disabled=true;
    if(!filename)return;
    try {
      const response=await fetch('/api/scenario-ir-budget?filename='+encodeURIComponent(filename),{cache:'no-store'});
      const data=await response.json();
      if(request!==budgetRequest)return;
      if(!response.ok)throw new Error(data.error||'예산 산정 실패');
      showBudget(data.budget);get('generate').disabled=busy;
    } catch(error) {if(request===budgetRequest){get('settings').textContent=error.message;throw error;}}
  }
  async function refresh(selected) {
    if (location.protocol === 'file:') { status('로컬 서버로 열어야 IR을 생성할 수 있습니다.'); return; }
    const r = await fetch('/api/approved-selections');
    if (!r.ok) throw new Error('승인본 목록 조회 실패');
    const data = await r.json();
    if (!Object.keys(defaults).length) {
      defaults = data.defaults;
      defaultOptions=data.default_generation_options||{...emptyOptions(),stop_retry:data.default_generation_mode==='validated'};
      get('settings').textContent='STEP 문서 로드 필요';
      reset();
    }
    const before = selected || get('files').value;
    get('files').replaceChildren(...data.files.filter(x=>x.approval_status==='approved').map(x=> {
      const o=document.createElement('option'); o.value=x.filename; o.textContent=x.filename+' · '+x.original_question; return o;
    }));
    if (before) get('files').value=before;
    await loadBudget();
  }
  function table(title, headings, rows) {
    const section=document.createElement('div');
    const h=document.createElement('h3'); h.textContent=title; section.append(h);
    const wrap=document.createElement('div');wrap.style.overflowX='auto';
    const t=document.createElement('table');
    [headings,...rows].forEach((row,i)=>{const tr=document.createElement('tr');row.forEach(value=>{const c=document.createElement(i?'td':'th');c.textContent=typeof value==='object'?JSON.stringify(value):String(value??'');tr.append(c);});t.append(tr);});
    wrap.append(t);section.append(wrap);return section;
  }
  const changeLabels={replace:'대체',unchanged:'동일 · 유지',response_binding:'응답 참조',input_needed:'입력 필요',comparison_unavailable:'비교 불가'};
  function resetSteps() {
    stepEntries.clear();selectedStepId=null;xmlView='after';
    get('step-list').replaceChildren();get('step-empty').hidden=false;get('step-detail').hidden=true;
  }
  function ensureStep(meta) {
    const id=meta.step_id||meta.step?.step_id;if(!id)return null;
    let entry=stepEntries.get(id);
    if(!entry){
      const button=document.createElement('button');button.type='button';button.className='ir-step-node';button.dataset.stepId=id;
      const task=document.createElement('span'),title=document.createElement('strong'),state=document.createElement('span');
      task.className='ir-step-kicker';state.className='ir-step-state';button.append(task,title,state);
      entry={id,s:{step_id:id,api:{},inputs:[],bindings:[]},status:'대기',button,taskLabel:task,titleLabel:title,stateLabel:state};
      stepEntries.set(id,entry);get('step-list').append(button);
      button.addEventListener('click',()=>{selectedStepId=id;renderStepSelection();});
      if(selectedStepId===null)selectedStepId=id;
    }
    const priorApi=entry.s.api;
    if(meta.step)entry.s={...entry.s,...meta.step,api:{...priorApi,...meta.step.api}};
    if(meta.api)entry.s.api={...entry.s.api,...meta.api};
    if(meta.edge!==undefined)entry.s.edge=meta.edge;
    for(const key of ['task_sequence','task_action','conditions','preview','status'])if(meta[key]!==undefined)entry[key]=meta[key];
    entry.taskLabel.textContent='업무 '+(entry.task_sequence??'—')+' · STEP '+id;
    entry.titleLabel.textContent=entry.s.edge||'단계 준비';entry.stateLabel.textContent=entry.status;
    entry.button.setAttribute('aria-pressed',String(selectedStepId===id));
    get('step-empty').hidden=true;return entry;
  }
  function updateSteps(event) {
    if(event.event==='scenario_steps'){
      event.steps.forEach(ensureStep);renderStepSelection();return;
    }
    let entry=event.step_id?stepEntries.get(event.step_id):null;
    if(event.event==='llm_request'){
      try{
        const input=event.input||event.messages||[];
        const payload=JSON.parse(input.find(x=>x.role==='user')?.content||'{}');
        if(payload.current_step)entry=ensureStep({...payload.current_step,task_sequence:payload.intent_task?.sequence,
          task_action:payload.intent_task?.action,conditions:payload.intent_task?.conditions});
      }catch(_){}
      if(entry)entry=ensureStep({step_id:entry.id,status:'분석 중'});
    }
    if(event.event==='backend_canonical')entry=ensureStep({step_id:event.step_id,api:event.result});
    if(event.event==='step_complete'&&entry)entry=ensureStep({step_id:entry.id,status:'초안 작성 · 비교 중',step:event.result});
    if(event.event==='backend_baseline_compare'&&entry)entry.s.inputs=event.result.comparisons||[];
    if(event.event==='step_preview')entry=ensureStep({...event,status:'초안 완료'+(event.step.unresolved?.length?' · 확인 필요':'')});
    if(event.event==='backend_output_defined'){
      const source=stepEntries.get(event.result?.step_id);
      if(source){source.s.outputs=source.s.outputs||[];if(!source.s.outputs.some(o=>o.name===event.result.output.name))source.s.outputs.push(event.result.output);}
    }
    if(['generation_error','llm_error'].includes(event.event)){
      for(const item of stepEntries.values())if(['분석 중','초안 작성 · 비교 중'].includes(item.status))ensureStep({step_id:item.id,status:'생성 실패'});
      if(activeMode==='validated')for(const item of stepEntries.values())if(item.status.startsWith('초안 완료'))ensureStep({step_id:item.id,status:'중간 결과 · 전체 생성 실패'});
    }
    if(entry?.id===selectedStepId||['backend_output_defined','generation_error','llm_error'].includes(event.event))renderStepSelection();
  }
  function renderStepSelection() {
    const entry=stepEntries.get(selectedStepId);get('step-detail').hidden=!entry;
    if(!entry)return;
    for(const item of stepEntries.values())item.button.setAttribute('aria-pressed',String(item.id===entry.id));
    get('step-title').textContent='STEP '+entry.id+' · '+(entry.s.edge||'단계 준비');
    get('step-state').textContent=entry.status;
    get('step-task').textContent='업무 '+(entry.task_sequence??'—')+' · '+(entry.task_action||'');
    get('step-condition').textContent=typeof entry.conditions==='object'&&entry.conditions!==null?JSON.stringify(entry.conditions,null,2):(entry.conditions||'업무 조건이 없습니다.');
    const api=get('step-api');api.replaceChildren();
    for(const [label,value] of [['API ID',entry.s.api.api_id],['Method',entry.s.api.method],['처리 구분값',entry.s.api.selector],['Endpoint',entry.s.api.endpoint]]){
      const item=document.createElement('div'),name=document.createElement('span'),text=document.createElement('code');
      name.className='ir-step-kicker';name.textContent=label;text.textContent=typeof value==='object'&&value!==null?JSON.stringify(value):String(value??'—');item.append(name,text);api.append(item);
    }
    const bindings=new Map((entry.s.bindings||[]).map(b=>[b.binding_id,b.from]));
    const rows=(entry.s.inputs||[]).map(input=>{
      const from=bindings.get(input.ref);
      const value=input.source==='bind'?(from?'{{'+from.from_step_id+'.'+from.output_name+'}}':'연결 미정'):
        ['unresolved','run_input'].includes(input.source)?'입력 필요':input.value;
      return [input.field||input.parameter_path,input.baseline_present===false?'기준 없음':input.baseline_value===null?'null':input.baseline_value,
              value,[changeLabels[input.change_kind]||input.change_kind,input.comparison_reason].filter(Boolean).join(' · ')];
    });
    get('step-parameters').replaceChildren(table('대체 파라미터',['파라미터','Baseline 값','적용 값 / 참조','처리'],rows));
    get('step-xml-source').textContent=entry.s.baseline?.validation_status||'';
    renderStepXML();
  }
  function renderStepXML() {
    const entry=stepEntries.get(selectedStepId),code=get('step-xml-code');code.replaceChildren();
    get('xml-after').setAttribute('aria-selected',String(xmlView==='after'));
    get('xml-before').setAttribute('aria-selected',String(xmlView==='before'));
    get('step-xml-panel').setAttribute('aria-labelledby',xmlView==='after'?'irDraftXMLAfter':'irDraftXMLBefore');
    if(!entry)return;
    const preview=entry.preview;
    get('step-xml-note').textContent='{{…}}는 실행 시 결정될 응답 참조 또는 필요한 입력을 표시합니다. 원본 Baseline은 수정하지 않습니다.';
    if(!preview?.available){
      code.textContent=preview?.warnings?.join('\n')||(['대기','분석 중','초안 작성 · 비교 중'].includes(entry.status)?'STEP 생성 후 XML 미리보기를 표시합니다.':'이 결과에는 Baseline XML 미리보기 정보가 없습니다. 다시 생성해 확인하세요.');
      return;
    }
    const lines=xmlView==='after'?preview.applied_lines:preview.original_xml.split('\n').map(text=>({text,changed:false}));
    for(const line of lines){
      const span=document.createElement('span');if(line.changed)span.className='ir-xml-change';
      const pattern=/<[^>]+>/g;let end=0;
      for(const match of line.text.matchAll(pattern)){
        span.append(document.createTextNode(line.text.slice(end,match.index)));
        const tag=document.createElement('span');tag.className='ir-xml-tag';tag.textContent=match[0];span.append(tag);end=match.index+match[0].length;
      }
      span.append(document.createTextNode(line.text.slice(end)));code.append(span,document.createTextNode('\n'));
    }
    if(preview.warnings?.length)get('step-xml-note').textContent+=' '+preview.warnings.join(' ');
  }
  for(const view of ['after','before']){
    const button=get('xml-'+view);
    button.addEventListener('click',()=>{xmlView=view;renderStepXML();});
    button.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();xmlView=event.key==='Home'?'after':event.key==='End'?'before':view==='after'?'before':'after';
      get('xml-'+xmlView).focus();renderStepXML();
    });
  }
  function preview(data) {
    get('mode-status').textContent='결과 옵션: '+describeOptions(resultOptions(data.ir.generation));
    for(const task of data.ir.tasks)for(const step of task.steps)ensureStep({step_id:step.step_id,step,task_sequence:task.sequence,
      task_action:task.action,conditions:task.conditions,preview:data.step_previews?.[step.step_id],status:'초안 완료'+(step.unresolved?.length?' · 확인 필요':'')});
    renderStepSelection();
    const out=get('result');out.replaceChildren();
    const summary=document.createElement('p');summary.textContent=data.ir.scenario_id+' v'+data.ir.version+' · '+data.ir.status+' · 저장: '+data.file;out.append(summary);
    const details=document.createElement('details'),title=document.createElement('summary'),pre=document.createElement('pre'),code=document.createElement('code');
    details.className='ir-json-view';title.textContent='IR JSON · Beautify';pre.append(code);details.append(title,pre);beautify(data.ir,code);out.append(details);
  }
  let currentReview=null,reviewBusy=false;
  const reviewControls=new Map();
  async function reviewRequest(url,body){
    const response=await fetch(url,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'검토 요청 실패');
    return data;
  }
  async function loadReviews(selected){
    const data=await reviewRequest('/api/scenario-ir-reviews');
    const prior=selected||get('reviews').value;
    get('reviews').replaceChildren(...data.reviews.map(row=>{
      const option=document.createElement('option');option.value=row.scenario_id;
      option.textContent=row.scenario_id+' · '+row.review.status+' · '+row.original_question;return option;
    }));
    if(prior)get('reviews').value=prior;
  }
  function showReview(data){
    currentReview=data;reviewControls.clear();
    const area=get('review-content');area.replaceChildren();
    const summary=document.createElement('p'),r=data.review;
    summary.textContent='검토 '+r.status+' · revision '+r.revision+' · 보류 '+r.open_count+' · 지금 입력 '+r.resolved_count+' · 실행 시 입력 '+r.deferred_count;
    area.append(summary);
    for(const target of data.targets){
      const box=document.createElement('fieldset'),legend=document.createElement('legend');
      legend.textContent=(target.step_id?'STEP '+target.step_id+' · ':'')+target.label;
      const note=document.createElement('p');
      note.textContent=[target.api_id,target.parameter_path,'타입: '+(target.type||'미확정'),
        'Baseline: '+JSON.stringify(target.baseline_value??null)+' ('+(target.baseline_value_source||'출처 없음')+')',...target.reasons].filter(Boolean).join(' · ');
      const choiceLabel=document.createElement('label'),choice=document.createElement('select');
      choiceLabel.textContent='입력 시점 ';choice.setAttribute('aria-label',target.label+' 입력 시점');
      for(const [value,text] of [['hold','검토 보류'],['now','지금 입력'],['runtime','실행 시 입력']]){
        if(!target.editable&&value!=='hold')continue;
        const option=document.createElement('option');option.value=value;option.textContent=text;choice.append(option);
      }
      const prior=data.decisions[target.target_id]||{choice:'hold'};choice.value=prior.choice;
      const isSelect=Boolean(target.enum?.length)||target.type==='boolean';
      const input=document.createElement(isSelect?'select':'input');
      input.setAttribute('aria-label',target.label+' 값');
      if(isSelect){
        const blank=document.createElement('option');blank.value='';blank.textContent='값 선택';input.append(blank);
        for(const value of target.enum?.length?target.enum:[true,false]){
          const option=document.createElement('option');option.value=JSON.stringify(value);option.textContent=String(value);input.append(option);
        }
      }else input.type=['integer','number'].includes(target.type)?'number':'text';
      if(input.type==='number')input.step=target.type==='integer'?'1':'any';
      input.value=prior.choice==='now'?(isSelect?JSON.stringify(prior.value):String(prior.value)):'';
      const update=()=>{input.disabled=choice.value!=='now'||r.status==='confirmed';};
      choice.addEventListener('change',update);choice.disabled=!target.editable||r.status==='confirmed';update();
      choiceLabel.append(choice);box.append(legend,note,choiceLabel,input);
      if(!target.editable){const info=document.createElement('p');info.textContent='값만 입력해 해결할 수 없습니다. 원본 조건·매핑 관계를 검토하고 다시 생성하세요.';box.append(info);}
      area.append(box);reviewControls.set(target.target_id,{target,choice,input,isSelect});
    }
    const shownIssues=new Set(data.targets.flatMap(target=>target.issue_ids||[]));
    for(const issue of data.ir.unresolved||[]){
      if(issue.status!=='open'||shownIssues.has(issue.issue_id))continue;
      const note=document.createElement('p');note.textContent='재검토 필요: '+issue.reason+' · '+(issue.required_input||'원본 조건을 검토하고 다시 생성하세요.');area.append(note);
    }
    const save=document.createElement('button'),confirm=document.createElement('button');
    save.type=confirm.type='button';save.className=confirm.className='btn';
    save.textContent='검토 저장';confirm.textContent='결정본 확정';
    save.disabled=r.status==='confirmed';confirm.disabled=r.status!=='ready_for_confirmation';
    for(const {choice,input} of reviewControls.values()){
      const dirty=()=>{confirm.disabled=true;get('review-status').textContent='변경한 선택을 먼저 검토 저장하세요.';};
      choice.addEventListener('change',()=>{input.disabled=choice.value!=='now'||r.status==='confirmed';dirty();});
      input.addEventListener('input',dirty);input.addEventListener('change',dirty);
    }
    save.addEventListener('click',()=>saveReview(false));confirm.addEventListener('click',()=>saveReview(true));
    area.append(save,confirm);
    if(r.status!=='confirmed'){const help=document.createElement('p');help.textContent='선택을 바꾼 뒤 검토 저장을 누르세요. 보류 항목이 없으면 저장된 결정을 확정할 수 있습니다.';area.append(help);}
    get('review-status').textContent='검토 상태를 불러왔습니다. 선택한 내용은 검토 저장 후 반영됩니다.';
  }
  async function saveReview(confirm){
    if(reviewBusy||busy||!currentReview)return;
    reviewBusy=true;
    try{
      const body={expected_revision:currentReview.review.revision};
      if(!confirm)body.decisions=[...reviewControls].map(([target_id,{target,choice,input,isSelect}])=>{
        const result={target_id,choice:choice.value};
        if(choice.value==='now'){
          if(input.value==='')throw new Error(target.label+': 값을 입력하세요');
          result.value=isSelect||target.type!=='string'?JSON.parse(input.value):input.value;
        }
        return result;
      });
      const id=currentReview.ir.scenario_id;
      const data=await reviewRequest('/api/scenario-ir-reviews/'+encodeURIComponent(id)+'/'+(confirm?'confirm':'decisions'),body);
      preview(data);showReview(data);await loadReviews(id);
      get('review-status').textContent=confirm?'결정본을 확정했습니다. 실제 업무 API는 실행하지 않았습니다.':'검토 내용을 저장했습니다.';
    }catch(error){get('review-status').textContent=error.message+' · 오래된 버전이면 검토 불러오기를 눌러 갱신하세요.';}
    finally{reviewBusy=false;}
  }
  async function generate(filename) {
    if (busy||reviewBusy) return;
    busy=true;get('files').disabled=true;get('generate').disabled=true;lockOptions(true);get('reset').disabled=true;
    get('result').replaceChildren();resetSteps();
    get('log-file').replaceChildren();
    logBody=resetLog();
    lastEvent={};started=performance.now();
    const clock=setInterval(progress,250);
    progress();
    try {
      const chosenOptions=readOptions();

      await refresh(filename);
      const chosen=filename||get('files').value;
      if (!chosen) throw new Error('승인본을 선택하세요. 로컬 서버 연결을 확인하세요.');
      if(!loadedBudget)throw new Error("예산 산정이 필요합니다");
      activeOptions={...chosenOptions};activeMode=activeOptions.stop_retry?'validated':'basic';writeOptions(activeOptions);
      get('mode-status').textContent='실행 옵션: '+describeOptions(activeOptions);
      status('승인 JSON 저장 완료 · IR 초안 생성 중…');
      const r=await fetch('/api/scenario-ir-drafts',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/x-ndjson'},body:JSON.stringify({approved_filename:chosen,generation_options:activeOptions})});
      const data=await receive(r);
      showLogFile(data);preview(data);if(data.review){showReview(data);await loadReviews(data.ir.scenario_id);}else{currentReview=null;get('review-content').replaceChildren();get('review-status').textContent='이 실행은 IR 입력 검토를 적용하지 않았습니다.';}status('IR 초안 저장 완료 · 실행용 시나리오에는 등록하지 않았습니다.');
    } catch(e) {
      updateSteps({event:'generation_error'});
      for(const row of logRows.values()){
        if(row.seconds===undefined){row.seconds=(performance.now()-row.started)/1000;row.state='중단 / 실패';row.response={error:e.message};renderRow(row);}
      }
      get('mode-status').textContent='실패한 실행 옵션: '+describeOptions(activeOptions);
      status('IR 생성 실패: '+e.message+' · 승인 파일은 유지됩니다.');}
    finally {clearInterval(clock);progress();await loadRunSummaries().catch(e=>{get('runs-status').textContent=e.message;});busy=false;get('files').disabled=false;get('generate').disabled=!loadedBudget;lockOptions(false);get('reset').disabled=false;}
  }
  for(const key of Object.keys(optionLabels))get('option-'+key).addEventListener('change',syncOptionDependencies);
  syncOptionDependencies();
  get('review-load').addEventListener('click',async()=>{
    if(busy||reviewBusy)return;
    try{const id=get('reviews').value;if(!id)throw new Error('검토 초안을 선택하세요');
      const data=await reviewRequest('/api/scenario-ir-reviews/'+encodeURIComponent(id));resetSteps();preview(data);showReview(data);
    }catch(error){get('review-status').textContent=error.message;}
  });
  loadReviews().catch(error=>{get('review-status').textContent=error.message;});
  resetSteps();
  get('files').addEventListener('change',()=>loadBudget().catch(e=>status(e.message)));
  for(const key of ['filter-from','filter-to','filter-options',...Object.keys(optionLabels).map(key=>'filter-'+key)])
    get(key).addEventListener('change',applyRunFilters);
  get('filter-reset').addEventListener('click',()=>{
    get('filter-from').value='';get('filter-to').value='';get('filter-options').checked=false;
    for(const key of Object.keys(optionLabels))get('filter-'+key).checked=false;
    applyRunFilters();
  });
  get('generate').addEventListener('click',()=>generate());
  get('reset').addEventListener('click',reset);
  window.ScenarioIRDraft={generate};
  refresh().catch(e=>status(e.message));
  loadRunSummaries().catch(e=>{get('runs-status').textContent=e.message;});
}());
