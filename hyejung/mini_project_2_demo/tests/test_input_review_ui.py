"""Browser option dependency and saved-decision workflow using a small DOM."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest


def test_review_controls_and_option_dependency():
    node=shutil.which('node')
    if not node:
        path=Path('/mnt/c/Program Files/nodejs/node.exe')
        node=str(path) if path.exists() else None
    if not node:pytest.skip('Node runtime not installed')
    source=(Path(__file__).resolve().parents[1]/'prototype/scenario-ir-draft.js').read_text()
    setup=r'''
const assert=require('node:assert/strict');
class Element {
 constructor(){this.children=[];this.controls={};this.events={};this.value='';this._text='';this.dataset={};this.attrs={};}
 set textContent(v){this._text=String(v);this.children=[];}
 get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
 setAttribute(k,v){this.attrs[k]=v;} focus(){}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;this._text='';}
 querySelector(key){return this.controls[key]??=new Element();}
 addEventListener(key,fn){this.events[key]=fn;}
 get style(){return {};}
}
const host=new Element();global.document={createElement:()=>new Element(),createTextNode:text=>({textContent:text}),getElementById:id=>id==='scenarioIRDraft'?host:null};
global.window={};global.location={protocol:'http:'};
const id='SCN-20261103-abcdef123456';
const options={stop_retry:true,approval_gate:true,injection_guard:true,kb_rag:false,dependency_projection:false};
let review={ir:{scenario_id:id,version:1,status:'needs_input',tasks:[{sequence:1,action:'조회',conditions:'조건',steps:[{step_id:'1-1',edge:'조회',api:{api_id:'demo'},inputs:[],outputs:[],bindings:[],unresolved:['u']}]}],generation:{options}},review:{revision:1,status:'awaiting_decision',open_count:1,resolved_count:0,deferred_count:0},targets:[{target_id:'t1',step_id:'1-1',api_id:'demo',parameter_path:'$.code',label:'고객코드',type:'string',enum:null,reasons:['값 필요'],editable:true}],decisions:{},file:'draft.json',step_previews:{}};
const posts=[];global.fetch=async(url,request)=>{
 if(url==='/api/approved-selections')return {ok:true,json:async()=>({defaults:{},files:[]})};
 if(url.startsWith('/api/scenario-ir-budget'))return {ok:true,json:async()=>({budget:null})};
 if(url==='/api/scenario-ir-log-summaries')return {ok:true,json:async()=>({runs:[]})};
 if(url==='/api/scenario-ir-reviews')return {ok:true,json:async()=>({reviews:[{scenario_id:id,review:review.review,original_question:'주문'}]})};
 if(url==='/api/scenario-ir-reviews/'+id)return {ok:true,json:async()=>structuredClone(review)};
 const body=JSON.parse(request.body);posts.push({url,body});
 assert.equal(body.expected_revision,review.review.revision);
 review.review.revision++;review.ir.version++;
 if(url.endsWith('/decisions')){
   review.decisions={t1:body.decisions[0]};
   review.review.status='ready_for_confirmation';review.review.open_count=0;review.review.resolved_count=1;
 }else{assert.ok(url.endsWith('/confirm'));review.review.status='confirmed';}
 return {ok:true,json:async()=>structuredClone(review)};
};
'''
    checks=r'''
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 const get=key=>host.querySelector('[data-'+key+']');
 assert.equal(get('option-injection_guard').disabled,true);
 get('option-stop_retry').checked=true;get('option-stop_retry').events.change();
 assert.equal(get('option-injection_guard').disabled,true);
 get('option-approval_gate').checked=true;get('option-approval_gate').events.change();
 assert.equal(get('option-injection_guard').disabled,false);
 get('option-injection_guard').checked=true;
 get('option-approval_gate').checked=false;get('option-approval_gate').events.change();
 assert.equal(get('option-injection_guard').checked,false);assert.equal(get('option-injection_guard').disabled,true);
 get('option-approval_gate').checked=true;get('option-approval_gate').events.change();
 assert.equal(get('option-injection_guard').checked,false);
 get('option-injection_guard').checked=true;get('option-stop_retry').checked=false;get('option-stop_retry').events.change();
 assert.equal(get('option-injection_guard').checked,false);assert.equal(get('option-injection_guard').disabled,true);
 get('reviews').value=id;await get('review-load').events.click();
 let content=get('review-content');
 let box=content.children[1],choice=box.children[2].children[0],input=box.children[3];
 assert.equal(choice.value,'hold');assert.equal(input.disabled,true);
 let save=content.children[2],confirm=content.children[3];
 assert.equal(confirm.disabled,true);
 choice.value='now';choice.events.change();assert.equal(input.disabled,false);
 input.value='000012';input.events.input();await save.events.click();
 assert.deepEqual(posts[0].body.decisions,[{target_id:'t1',choice:'now',value:'000012'}]);
 assert.equal(get('review-content').children[3].disabled,false);
 // An unsaved change must prevent confirming the older saved choice.
 content=get('review-content');box=content.children[1];input=box.children[3];input.value='000013';input.events.input();
 assert.equal(content.children[3].disabled,true);
 await get('review-load').events.click();
 content=get('review-content');assert.equal(content.children[1].children[3].value,'000012');
 await content.children[3].events.click();
 assert.equal(posts[1].url.endsWith('/confirm'),true);
 assert.equal(get('review-content').children[2].disabled,true);
 assert.match(get('review-status').textContent,/결정본을 확정/);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    run=subprocess.run([node],input=setup+'\n'+source+'\n'+checks,text=True,capture_output=True,timeout=20)
    assert run.returncode==0,run.stdout+run.stderr
