"""Exercise the browser stream consumer with split UTF-8 chunks in a small DOM stub."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_progress_ui_stream_chunks_and_failure():
    node = shutil.which('node')
    if not node:
        candidate = Path('/mnt/c/Program Files/nodejs/node.exe')
        node = str(candidate) if candidate.exists() else None
    if not node:
        pytest.skip('Node runtime not installed')
    source = (Path(__file__).resolve().parents[1]/'prototype/scenario-ir-draft.js').read_text()
    setup = r'''
const assert=require('node:assert/strict');
class Element {
 constructor(){this.children=[];this.controls={};this.events={};this.value='';this._text='';this.dataset={};this.attrs={};}
 set textContent(v){this._text=String(v);this.children=[];}
 get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
 setAttribute(k,v){this.attrs[k]=v;}
 focus(){this.focused=true;}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;this._text='';}
 querySelector(key){return this.controls[key]??=(new Element());}
 addEventListener(key,fn){this.events[key]=fn;}
 insertAdjacentElement(){}
 get childElementCount(){return this.children.length;}
 set style(value){} get style(){return {};}
}
const host=new Element();
global.document={createElement:()=>new Element(),createTextNode:text=>({textContent:text}),getElementById:id=>id==='scenarioIRDraft'?host:null};
global.window={};global.location={protocol:'http:'};
let failed=false, duringChecks=false;const requestedModes=[],requestedOptions=[];
const defaults={max_turns:16,max_tokens:150000,max_seconds:180,max_output_tokens:4096};
const result={file:'data/out/example.json',usage:{total_tokens:12,input_tokens:8,output_tokens:4},ir:{scenario_id:'demo',version:1,status:'needs_input',tasks:[{sequence:1,conditions:'협력사 코드 조건',depends_on:[],steps:[{step_id:'1-1',api:{api_id:'api-1'},inputs:[{parameter_path:'$.venCd',value:'001442',baseline_value:null,baseline_present:false,change_kind:'comparison_unavailable',reason:'조건 매핑',comparison_reason:'Baseline 경로 없음'}],outputs:[],bindings:[],assertions:[]}]}],unresolved:[],final_outputs:[],sources:{},generation:{mode:'baseline_replacements'}}};

result.ir.tasks[0].action='주문조회';result.ir.tasks[0].steps[0].edge='주문 조회';
const second={step_id:'2-1',edge:'주문 확인',api:{api_id:'api-2',method:'POST',endpoint:'/process'},
 inputs:[{field:'ordNo',parameter_path:'$.ordNo',source:'bind',ref:'B-1',value:null,baseline_value:'EXAMPLE',change_kind:'response_binding'}],
 bindings:[{binding_id:'B-1',from:{from_step_id:'1-1',output_name:'ordNo'},to_parameter_path:'$.ordNo'}],outputs:[],assertions:[],unresolved:[]};
result.ir.tasks.push({sequence:2,action:'주문 처리',conditions:'1번 업무의 조회 결과로 주문 처리',steps:[second]});
const makePreview=(field,original,value)=>{
 const lines=['<Root>','  <'+field+'>'+value+'</'+field+'>','</Root>'];
 return {available:true,original_xml:'<Root>\n  <'+field+'>'+original+'</'+field+'>\n</Root>',applied_xml:lines.join('\n'),
 applied_lines:lines.map((text,i)=>({text,changed:i===1})),warnings:[]};
};
result.step_previews={'1-1':makePreview('venCd','003766','001442'),'2-1':makePreview('ordNo','EXAMPLE','{{1-1.ordNo}}')};
const planned=[{step_id:'1-1',edge:'주문 조회',task_sequence:1,task_action:'주문조회',conditions:'협력사 코드 조건',api:{api_id:'api-1'}},
 {step_id:'2-1',edge:'주문 확인',task_sequence:2,task_action:'주문 처리',conditions:'1번 업무의 조회 결과로 주문 처리',api:{api_id:'api-2'}}];
global.fetch=async(url,options)=>{
 if(url.startsWith('/api/scenario-ir-budget?'))return {ok:true,json:async()=>({budget:{step_count:2,limits:{llm_calls:12,tokens:130000,seconds:150}}})};
 if(url==='/api/approved-selections')return {ok:true,json:async()=>({defaults,files:[{filename:'approved.json',original_question:'주문',approval_status:'approved'}]})};
 if(url==='/api/scenario-ir-reviews')return {ok:true,json:async()=>({reviews:[]})};
 if(url==='/api/scenario-ir-log-summaries')return {ok:true,json:async()=>({runs:[{run_id:'IRRUN-example',filename:'IRRUN-example.jsonl',started_at:'2026-11-01T10:00:00+09:00',options:{stop_retry:false,kb_rag:true,dependency_projection:true},status:'완료',duration_seconds:65,model_calls:3,turns:3,input_tokens:800,output_tokens:120,embedding_tokens:20,total_tokens:940}]})};
 assert.equal(options.headers.Accept,'application/x-ndjson');
 const selected=JSON.parse(options.body).generation_options;requestedOptions.push(selected);
 const mode=selected.stop_retry?'validated':'basic';requestedModes.push(mode);
 for(const key of ['stop_retry','kb_rag','dependency_projection'])assert.equal(typeof selected[key],'boolean');
 result.ir.generation.options=selected;
 for(const key of ['stop_retry','kb_rag','dependency_projection'])assert.equal(host.querySelector('[data-option-'+key+']').disabled,true);
 if(mode==='validated')result.ir.generation.execution_mode='validated';
 const events=[{event:'generation_start',log_file:'data/out/scenario_ir_logs/IRRUN-example.jsonl',log_url:'/api/scenario-ir-logs/IRRUN-example.jsonl'},{event:'llm_request',turn:0,next_turn:1,step_id:'1-1',step_turn:1,instructions:'공통 역할',input:[{role:'user',content:'한글 프롬프트'}],text:{format:{type:'json_schema',strict:true}},store:false,include:['reasoning.encrypted_content']},
 {event:'llm_response',turn:1,step_id:'1-1',usage:result.usage,response_status:'completed',output:{object:'response',status:'completed',output:[{type:'message',content:[{type:'output_text',text:'한글 결과'}]}]}},
 {event:'tool_selected',turn:1,step_id:'1-1',call_id:'read',tool:'get_request_schema',arguments:'{}'},
 {event:'tool_start',turn:1,step_id:'1-1',call_id:'read',tool:'get_request_schema'},
 {event:'tool_result',turn:1,step_id:'1-1',call_id:'read',tool:'get_request_schema',tool_seconds:0.01,result:{data:{}}},
 {event:'tool_selected',turn:1,step_id:'1-1',call_id:'bad',tool:'validate_mapping',arguments:'{}'},
 {event:'tool_result',turn:1,step_id:'1-1',call_id:'bad',tool:'validate_mapping',tool_seconds:0.02,result:{valid:false,errors:[{message:'bad'}]}},
 {event:'tool_selected',turn:1,step_id:'1-1',call_id:'good',tool:'validate_mapping',arguments:JSON.stringify({step_id:'1-1',value:'001442'})},
 {event:'tool_result',turn:1,step_id:'1-1',call_id:'good',tool:'validate_mapping',tool_seconds:0.03,result:{valid:true,errors:[]}}];
 events.push({event:'backend_canonical',step_id:'1-1',turn:1,backend_seconds:0.001,request:{selected_api_id:'api-1'},result:{method:'POST'}},
 {event:'material_check',step_id:'1-1',turn:1,request:{selected_api_id:'api-1'},result:{provided:[{tool:'get_parameter_knowledge'}]}},
 {event:'backend_baseline_compare',step_id:'1-1',turn:1,backend_seconds:0.002,request:{selected_api_id:'api-1'},result:{comparisons:[{change_kind:'comparison_unavailable'}]}});
 events.push({event:'backend_output_defined',step_id:'2-1',turn:3,request:{source_step_id:'1-1'},result:{step_id:'1-1',output:{name:'ordNo',response_path:'/Response/row/ordNo'}}});
 if(mode==='validated')events.push(
 {event:'mapping_validation',step_id:'1-1',step_turn:2,turn:2,request:{candidate:{}},result:{valid:false,errors:[{code:'VALUE_TYPE_MISMATCH'}]}},
 {event:'mapping_validation',step_id:'1-1',step_turn:3,turn:3,request:{candidate:{}},result:{valid:true,errors:[]}},
 {event:'final_ir_validation',step_id:'2-1',turn:4,request:{scenario_id:'demo'},result:{valid:true,errors:[]}},
 {event:'llm_retry',step_id:'2-1',turn:4,request_id:'2-1:3',attempt:1,request:{wait_seconds:0.5},result:{wait_seconds:0.5}},
 {event:'llm_attempt_start',step_id:'2-1',turn:4,request_id:'2-1:3',attempt:2,request:{attempt:2}},
 {event:'llm_attempt_complete',step_id:'2-1',turn:4,request_id:'2-1:3',attempt:2,backend_seconds:0.04,result:{status:'completed'}});
 events.push(failed?{event:'generation_error',error:'한글 오류'}:{event:'generation_complete',result});
 events.splice(1,0,{event:'scenario_steps',steps:planned});
 events.splice(events.length-1,0,{event:'step_preview',step_id:'1-1',step:result.ir.tasks[0].steps[0],task_sequence:1,task_action:'주문조회',conditions:'협력사 코드 조건',preview:result.step_previews['1-1']});
 const bytes=new TextEncoder().encode(events.map(x=>JSON.stringify(x)).join('\n')+'\n');let offset=0;
 return {ok:true,headers:{get:()=> 'application/x-ndjson'},body:{getReader:()=>({read:async()=>{
 const get=k=>host.querySelector('[data-'+k+']');
 const rows=get('log').children[0]?.children[1]?.children||[];
 if(!duringChecks && rows.length===1 && rows[0].children[4].textContent==='LLM 응답 대기'){
   duringChecks=true;
   assert.equal(get('step-list').children.length,2);
   assert.match(get('step-state').textContent,/분석 중/);
   get('step-list').children[1].events.click();
   assert.match(get('step-condition').textContent,/조회 결과로 주문 처리/);
   assert.match(get('step-xml-code').textContent,/생성 후/);
   assert.match(get('detail-json').textContent,/응답을 기다리고/);
   get('detail-request').events.click();
   assert.match(get('detail-json').textContent,/한글 프롬프트/);
   get('detail-response').events.click();
 }
 if(offset>=bytes.length)return {done:true};const value=bytes.slice(offset,offset+7);offset+=7;return {done:false,value};
 }})}};
};
'''
    checks = r'''
(async()=>{
 await window.ScenarioIRDraft.generate('approved.json');
 const get=k=>host.querySelector('[data-'+k+']');
 assert.match(get('status').textContent,/저장 완료/);
 assert.match(get('log-file').children[0].textContent,/IRRUN-example.jsonl/);
 assert.equal(get('log-file').children[1].href,'/api/scenario-ir-logs/IRRUN-example.jsonl');
 assert.match(get('progress').textContent,/누적 토큰 12/);
 assert.match(get('runs-status').textContent,/JSONL 로그 1 \/ 1개/);
 assert.match(get('runs-table').textContent,/2026/);
 assert.match(get('runs-table').textContent,/940/);
 const rows=get('log').children[0].children[1].children;
 assert.equal(rows.length,8); // one LLM row and one row per tool call, not per event
 assert.equal(rows[0].children.length,8);
 assert.equal(rows[1].children[7].textContent,'—');
 assert.equal(rows[2].children[7].textContent,'false');
 assert.equal(rows[3].children[7].textContent,'true');
 assert.equal(rows[3].children[5].textContent,'0.030초');
 assert.equal(duringChecks,true);
 assert.match(get('detail-json').textContent,/한글 결과/); // selected response updates live
 assert.equal(rows[0].dataset.selected,'true');
 get('detail-request').events.click();
 assert.match(get('detail-json').textContent,/한글 프롬프트/);
 rows[3].events.click();
 assert.equal(rows[0].dataset.selected,'false');
 assert.equal(rows[3].dataset.selected,'true');
 assert.match(get('detail-title').textContent,/validate_mapping/);
 assert.equal(get('detail-json').textContent,JSON.stringify({step_id:'1-1',value:'001442'},null,2));
 get('detail-response').events.click();
 assert.match(get('detail-json').textContent,/"valid": true/);
 assert.equal(get('detail-response').attrs['aria-selected'],'true');
 rows[2].events.click();
 assert.match(get('detail-json').textContent,/"valid": false/);
 get('detail-response').events.keydown({key:'ArrowLeft',preventDefault(){}});
 assert.equal(get('detail-request').focused,true);
 assert.equal(get('detail-json').textContent,'{}');
 get('detail-response').events.click();
 assert.ok(get('result').children.length>0);

 assert.equal(get('step-list').children[1].attrs['aria-pressed'],'true');
 assert.match(get('step-condition').textContent,/조회 결과로 주문 처리/);
 assert.match(get('step-api').textContent,/\/process/);
 assert.match(get('step-parameters').textContent,/응답 참조/);
 assert.match(get('step-xml-code').textContent,/\{\{1-1.ordNo\}\}/);
 get('xml-before').events.click();assert.match(get('step-xml-code').textContent,/EXAMPLE/);
 get('xml-after').events.click();assert.match(get('step-xml-code').textContent,/1-1.ordNo/);
 get('xml-after').events.keydown({key:'End',preventDefault(){}});assert.equal(get('xml-before').focused,true);
 get('step-list').children[0].events.click();assert.match(get('step-condition').textContent,/협력사 코드 조건/);
 assert.match(get('step-parameters').textContent,/비교 불가/);
 assert.match(get('step-xml-code').textContent,/003766/); // the XML tab remains on original
 get('xml-after').events.click();assert.match(get('step-xml-code').textContent,/001442/);
 assert.equal(get('result').children.length,2); // summary and final JSON only
 const jsonCode=get('result').children[1].children[1].children[0];
 assert.deepEqual(JSON.parse(jsonCode.textContent),result.ir);
 assert.ok(jsonCode.children.length>1);
 assert.equal(get('result').children[1].children[0].textContent,'IR JSON · Beautify');

 assert.equal(rows[7].children[6].textContent,'—');
 rows[7].events.click();
 assert.match(get('detail-title').textContent,/앞 STEP 출력 보완/);
 assert.match(get('detail-json').textContent,/ordNo/);
 assert.equal(rows[6].children[6].textContent,'—');
 rows[6].events.click();
 assert.match(get('detail-title').textContent,/백엔드/);
 assert.match(get('detail-json').textContent,/comparison_unavailable/);
 get('detail-request').events.click();
 assert.match(get('detail-json').textContent,/api-1/);
 get('detail-response').events.click();
 failed=true;
 await window.ScenarioIRDraft.generate('approved.json');
 assert.match(get('status').textContent,/한글 오류/);
 assert.match(get('log-file').children[0].textContent,/IRRUN-example.jsonl/);
 assert.equal(get('log').children[0].children[1].children.length,8);
 assert.equal(get('generate').disabled,false);
 assert.equal(get('result').children.length,0);
 assert.equal(get('step-list').children[0].attrs['aria-pressed'],'true');
 assert.match(get('step-condition').textContent,/협력사 코드 조건/);
 assert.match(get('detail-json').textContent,/한글 결과/); // new generation resets old selection
 assert.match(get('detail-title').textContent,/LLM/);
 failed=false;get('option-stop_retry').checked=true;
 await window.ScenarioIRDraft.generate('approved.json');
 assert.deepEqual(requestedModes,['basic','basic','validated']);
 assert.match(get('mode-status').textContent,/중지조건·재시도/);
 const modeRows=get('log').children[0].children[1].children;
 assert.equal(modeRows.length,13);
 assert.equal(modeRows[8].children[7].textContent,'false');
 assert.equal(modeRows[9].children[7].textContent,'true');
 assert.equal(modeRows[10].children[7].textContent,'true');
 modeRows[8].events.click();get('detail-response').events.click();
 assert.match(get('detail-json').textContent,/VALUE_TYPE_MISMATCH/);
 modeRows[11].events.click();assert.match(get('detail-json').textContent,/wait_seconds/);
 assert.equal(get('option-stop_retry').disabled,false);
 modeRows[12].events.click();get('detail-request').events.click();
 assert.match(get('detail-json').textContent,/"attempt": 2/);
 assert.equal(modeRows[12].children[5].textContent,'0.040초');
 get('reset').events.click();for(const key of ['stop_retry','kb_rag','dependency_projection'])assert.equal(get('option-'+key).checked,false);
 for(let mask=0;mask<8;mask++){
   const expected={stop_retry:Boolean(mask&4),kb_rag:Boolean(mask&2),dependency_projection:Boolean(mask&1)};
   for(const [key,value] of Object.entries(expected))get('option-'+key).checked=value;
   await window.ScenarioIRDraft.generate('approved.json');
   assert.deepEqual(requestedOptions.at(-1),expected);   // IR 입력 검토 옵션은 화면에 없음 (2026-11-05)
   for(const [key,value] of Object.entries(expected)){
     assert.equal(get('option-'+key).checked,value);assert.equal(get('option-'+key).disabled,false);
   }
   assert.equal(get('mode-status').textContent.includes('압축 1'),expected.kb_rag);
   assert.equal(get('mode-status').textContent.includes('압축 2'),expected.dependency_projection);
 }

})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    run = subprocess.run([node],input=setup+'\n'+source+'\n'+checks,text=True,capture_output=True,timeout=15)
    assert run.returncode == 0, run.stdout+run.stderr


def test_ir_region_is_full_width_sibling_after_editor():
    from html.parser import HTMLParser
    html=(Path(__file__).resolve().parents[1]/'prototype/offline-ui.html').read_text()
    class Layout(HTMLParser):
        def __init__(self): super().__init__();self.stack=[];self.ir_parent=None;self.ir_ancestors=[]
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if attrs.get('id')=='scenarioIRDraft':
                self.ir_parent=self.stack[-1][1].get('id')
                self.ir_ancestors=[a for _,a in self.stack]
            if tag not in ['area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr']:
                self.stack.append((tag,attrs))
        def handle_endtag(self,tag):
            for i in range(len(self.stack)-1,-1,-1):
                if self.stack[i][0]==tag:self.stack=self.stack[:i];break
    layout=Layout();layout.feed(html)
    assert layout.ir_parent=='panel-reg'
    assert not any(a.get('id') in ['regEditor','extractOut','confirmOut'] or 'reggrid' in a.get('class','').split() for a in layout.ir_ancestors)
    assert html.index('id="scenarioIRDraft"')>html.index('id="extractOut"')
