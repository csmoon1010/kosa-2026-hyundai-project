"""Mode isolation, bounded recovery and save gates without paid requests."""
import json
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from openai import OpenAI
try:
    import httpx2 as httpx
except ImportError:
    import httpx

from test_scenario_ir_drafts import (root, FILENAME, candidate, unit_plan, api_response,
                                     read_calls, empty_proposal, output_definition)
from tap.agent.config import configuration, generation_policy, harness_configuration
from tap.agent.parameter_tools import ParameterTools
from tap.agent.runtime import Runtime
from tap.agent.tool_registry import ToolRegistry
from tap.ir.draft_build import generate, fixed_plan
from tap.ir.draft_validate import FinalValidationError, validate_final_ir


def context(root, dependent=False):
    approved = json.loads((root/'data/ir_inputs'/FILENAME).read_text())
    return approved, ParameterTools(root, approved), (fixed_plan if dependent else unit_plan)(approved)


def fixed_candidate(tools, current):
    c = empty_proposal(current)
    field = next(x for x in candidate(tools, current, {})['inputs'] if x['field']=='venCd')
    field.update(source='fixed', origin='user_condition', value='001442',
                 evidence=[dict(source_id='approved', source_pointer='/original_question', quote='001442')])
    c['inputs'] = [field]
    return c


def queued_runtime(tools, responses, mode='validated'):
    requests = []
    def create(**kwargs):
        requests.append(deepcopy(kwargs))
        response = responses.pop(0)
        if isinstance(response, Exception): raise response
        return response
    runtime = Runtime(tools, configuration(), client=NS(responses=NS(create=create)), model='test', generation_mode=mode)
    events=[]; runtime.on_event=events.append
    return runtime, requests, events


def test_mode_config_snapshots_and_reject_unknown():
    assert generation_policy()[0]=='basic'
    basic = harness_configuration(); checked=harness_configuration(generation_mode='validated')
    assert basic['policy']['mapping_validation'] is False
    assert checked['policy']['mapping_repair_limit_per_step']==1
    assert '## 백엔드 검증과 복구' not in basic['instructions']
    assert '## 백엔드 검증과 복구' in checked['instructions']
    checked['policy']['llm_transport_max_retries']=9
    assert generation_policy('validated')[1]['llm_transport_max_retries']==1
    for mode in ('unknown', {}, True):
        with pytest.raises(ValueError): generation_policy(mode)


def test_sparse_validation_does_not_require_all_fields(root):
    a,tools,plan=context(root); c=fixed_candidate(tools,plan[0])
    assert tools.validate(c,plan[0],{})['valid']
    c['inputs']=[]
    assert tools.validate(c,plan[0],{})['valid']


@pytest.mark.parametrize('mutation,code', [
    ('path','PARAMETER_PATH_NOT_FOUND'), ('value','VALUE_TYPE_MISMATCH'),
    ('xml','PARAMETER_METADATA_MISMATCH'), ('duplicate','DUPLICATE_MAPPING'),
    ('evidence','EVIDENCE_MISMATCH')])
def test_candidate_errors_are_actionable(root, mutation, code):
    _,tools,plan=context(root); c=fixed_candidate(tools,plan[0]); item=c['inputs'][0]
    if mutation=='path': item['parameter_path']='$.does_not_exist'
    if mutation=='value': item['value']=1442
    if mutation=='xml': item['xml_path']='/wrong'
    if mutation=='duplicate': c['inputs'].append(deepcopy(item))
    if mutation=='evidence': item['evidence'][0]['quote']='not in original'
    if mutation=='assertion': c['assertions']=[{'name':'excluded'}]
    verdict=tools.validate(c,plan[0],{})
    error=next(e for e in verdict['errors'] if e['code']==code)
    assert error['item_path'].startswith('/') and 'actual' in error and 'expected' in error
    assert error['recovery']['action']=='REVISE_MAPPING'


def test_repair_once_and_adopt_without_confirmation_call(root):
    a,tools,plan=context(root); c=fixed_candidate(tools,plan[0]); bad=deepcopy(c)
    bad['inputs'][0]['value']=1442
    c['inputs'][0]['type']=None; c['inputs'][0]['xml_path']=None
    queue=[api_response(read_calls(tools,plan[0])), api_response(content=json.dumps(bad)), api_response(content=json.dumps(c))]
    runtime,requests,events=queued_runtime(tools,queue)
    result=runtime.run(plan[0],{},a['intent_tasks'][0],a['original_question'],[])
    assert result['inputs'][0]['value']=='001442' and result['inputs'][0]['type']=='string'
    assert len(requests)==3 and not queue
    feedback=json.loads(requests[-1]['input'][-1]['content'])
    assert feedback['repair_remaining']==0 and feedback['errors'][0]['code']=='VALUE_TYPE_MISMATCH'
    assert [e['result']['valid'] for e in events if e['event']=='mapping_validation']==[False,True]
    assert runtime.repair_counts=={'1-1':1}


def test_second_error_stops_even_when_error_code_changes(root):
    a,tools,plan=context(root); bad=fixed_candidate(tools,plan[0]); next_bad=deepcopy(bad)
    bad['inputs'][0]['value']=1442;next_bad['inputs'][0]['parameter_path']='$.bad'
    runtime,requests,events=queued_runtime(tools,[api_response(read_calls(tools,plan[0])),
        api_response(content=json.dumps(bad)),api_response(content=json.dumps(next_bad))])
    with pytest.raises(ValueError, match='수정 기회'):
        runtime.run(plan[0],{},a['intent_tasks'][0],a['original_question'],[])
    assert len(requests)==3 and events[-1]['event']=='recovery_stopped'


def test_material_fetch_does_not_consume_repair_and_no_progress_stops(root):
    a,tools,plan=context(root,True); current=plan[0]; c=empty_proposal(current)
    runtime,requests,events=queued_runtime(tools,[api_response(read_calls(tools,current)),
        api_response(content=json.dumps(c)),api_response(content=json.dumps(c))])
    with pytest.raises(ValueError, match='자료 부족'):
        runtime.run(current,{},a['intent_tasks'][0],a['original_question'],plan[1:])
    assert runtime.repair_counts=={}
    assert json.loads(requests[-1]['input'][-1]['content'])['recovery']['action']=='CALL_TOOL'


def test_known_business_uncertainty_can_finish_after_response_read(root):
    a,tools,plan=context(root,True); current=plan[0]; c=empty_proposal(current)
    c['unresolved']=[dict(dependency_ids=['D-1-to-2'],reason='응답 필드를 조회했지만 주문 대상 의미를 확정할 수 없음',
                          required_input='대상 필드',parameter_paths=[],evidence=[])]
    response_call=dict(type='function_call',id='response',call_id='response',name='get_response_outputs',
                       arguments=json.dumps({'selected_api_id':current['selected_api_id']}))
    runtime,requests,events=queued_runtime(tools,[api_response(read_calls(tools,current)),
        api_response([response_call]),api_response(content=json.dumps(c))])
    assert runtime.run(current,{},a['intent_tasks'][0],a['original_question'],plan[1:])==c
    assert runtime.repair_counts=={}


def test_failed_mapping_cannot_commit_upstream_output_patch(root):
    a,tools,plan=context(root,True); current=plan[1]; out=output_definition(tools,plan[0]['selected_api_id'])
    previous={'1-1':{'api':{'api_id':plan[0]['selected_api_id']},'outputs':[]}}
    registry=ToolRegistry(tools,current,previous,harness_configuration()['errors'],validated=True)
    registry.call_tool('get_parameter_knowledge',json.dumps({'selected_api_id':current['selected_api_id']}))
    registry.call_tool('get_response_outputs',json.dumps({'selected_api_id':plan[0]['selected_api_id']}))
    c=empty_proposal(current)
    field=next(x for x in candidate(tools,current,{})['inputs'] if x['field']=='ordNo')
    field.update(source='bind',origin='previous_output',ref='b'); c['inputs']=[field]
    c['bindings']=[dict(binding_id='b',to_parameter_path=field['parameter_path'],**{'from':dict(
        from_step_id='1-1',output_name='ordNo',**{k:out[k] for k in ['response_key','content_type','response_path','path_type','row_scope']})})]
    c['inputs'].append({**fixed_candidate(tools,current)['inputs'][0],'value':1442})
    assert registry.finish(json.dumps(c))[0] is None
    assert previous['1-1']['outputs']==[]


@pytest.mark.parametrize('mutation,code', [('scope','BINDING_SOURCE_MISMATCH'),
    ('forward','BINDING_SOURCE_MISMATCH'), ('target','BINDING_TARGET_MISMATCH'),
    ('ref','BINDING_TARGET_MISMATCH'), ('type','BINDING_TYPE_MISMATCH')])
def test_binding_checks_source_target_type_and_row_scope(root, mutation, code):
    a,tools,plan=context(root,True);current=plan[1];out=output_definition(tools,plan[0]['selected_api_id'])
    previous={'1-1':{'outputs':[out]}}
    c=empty_proposal(current)
    field=next(x for x in candidate(tools,current,{})['inputs'] if x['field']=='ordNo')
    field.update(source='bind',origin='previous_output',ref='b');c['inputs']=[field]
    binding=dict(binding_id='b',to_parameter_path=field['parameter_path'],**{'from':dict(
        from_step_id='1-1',output_name='ordNo',**{k:out[k] for k in ['response_key','content_type','response_path','path_type','row_scope']})})
    c['bindings']=[binding]
    assert tools.validate(c,current,previous)['valid']
    if mutation=='scope':binding['from']['row_scope']='row'
    if mutation=='forward':binding['from']['from_step_id']='2-3'
    if mutation=='target':binding['to_parameter_path']='$.missing'
    if mutation=='ref':field['ref']='missing'
    if mutation=='type':out['type']='integer'
    assert any(e['code']==code for e in tools.validate(c,current,previous)['errors'])


@pytest.mark.parametrize('status,code,expected_calls',[(503,'server_error',2),(429,'rate_limit_exceeded',2),
    (429,'insufficient_quota',1),(401,'invalid_api_key',1),(400,'invalid_request_error',1)])
def test_real_sdk_transport_retry_policy(root, status, code, expected_calls):
    a,tools,plan=context(root); current=plan[0]; calls=[]
    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls)==1:
            return httpx.Response(status, headers={'retry-after':'0'},json={'error':{'message':'offline error','type':code,'code':code}})
        return httpx.Response(200,json=api_response(content=json.dumps(empty_proposal(current))).model_dump(mode='json'))
    with OpenAI(api_key='offline-test',http_client=httpx.Client(transport=httpx.MockTransport(handler)),max_retries=5) as client:
        runtime=Runtime(tools,configuration(),client=client,model='test',generation_mode='validated')
        runtime.config['retry_base_seconds']=0
        # Satisfy KB first to isolate transport from model/tool decisions.
        initial=api_response(read_calls(tools,current)); counter=[0]
        original=runtime.client.responses.create
        def create(**kwargs):
            counter[0]+=1
            return initial if counter[0]==1 else original(**kwargs)
        runtime.client.responses.create=create
        if expected_calls==1:
            with pytest.raises(Exception): runtime.run(current,{},a['intent_tasks'][0],a['original_question'],[])
        else:
            runtime.run(current,{},a['intent_tasks'][0],a['original_question'],[])
    assert len(calls)==expected_calls
    if len(calls)==2: assert calls[0]==calls[1]


def test_timeout_retry_once_and_basic_no_retry(root):
    a,tools,plan=context(root); current=plan[0]
    for mode in ['basic','validated']:
        runtime,requests,events=queued_runtime(tools,[TimeoutError('temporary'),TimeoutError('still failing')],mode)
        runtime.config['retry_base_seconds']=0
        with pytest.raises(TimeoutError):runtime.run(current,{},a['intent_tasks'][0],a['original_question'],[])
        assert len(requests)==(2 if mode=='validated' else 1)


def scenario_queue(tools, plan):
    queue=[]
    response=tools.read('get_response_outputs',plan[0]['selected_api_id'])
    out=output_definition(tools,plan[0]['selected_api_id'])
    field=next(f for f in response['data']['outputs'] if f['name']=='ordNo')
    out['evidence']=[dict(source_id=response['source_id'],source_pointer=field['source_pointer']+'/response_path',quote=out['response_path'])]
    proposals={}
    for current in plan:
        c=empty_proposal(current)
        if current['step_id']=='1-1':
            c=fixed_candidate(tools,current);c['outputs']=[out]
        else:
            f=next(x for x in candidate(tools,current,{})['inputs'] if x['field']=='ordNo')
            f.update(source='bind',origin='previous_output',ref='b-'+current['step_id'])
            c['inputs']=[f]
            c['bindings']=[dict(binding_id=f['ref'],to_parameter_path=f['parameter_path'],**{'from':dict(
                from_step_id='1-1',output_name='ordNo',**{k:out[k] for k in ['response_key','content_type','response_path','path_type','row_scope']})})]
        queue.append(api_response(read_calls(tools,current)))
        if current['step_id']=='1-1':
            queue.append(api_response([dict(type='function_call',id='response',call_id='response',name='get_response_outputs',
                arguments=json.dumps({'selected_api_id':current['selected_api_id']}))]))
        queue.append(api_response(content=json.dumps(c)))
        proposals[current['step_id']]=deepcopy(c)
    return queue,proposals


def generate_checked(root, queue, events):
    def factory(tools, config):
        runtime,requests,_=queued_runtime(tools,queue)
        return runtime
    return generate(root,FILENAME,runtime_factory=factory,on_event=events.append,generation_mode='validated')


def test_validated_end_to_end_saves_after_final_gate(root):
    a,tools,plan=context(root,True); queue,_=scenario_queue(tools,plan);events=[]
    result=generate_checked(root,queue,events)
    ir=result['ir']
    assert not queue and ir['generation']['usage']['llm_calls']==9
    assert ir['generation']['execution_mode']=='validated' and ir['generation']['mode']=='baseline_replacements'
    assert ir['generation']['validation']==dict(mapping=True,required_fields=False,final_mapping=True)
    assert ir==json.loads((root/result['file']).read_text())
    assert sum(e['event']=='final_ir_validation' for e in events)==1
    assert sum(e['event']=='mapping_validation' for e in events)==4
    assert ir['tasks'][1]['depends_on']==[1]


def test_final_backend_error_does_not_call_llm_or_save(root, monkeypatch):
    import tap.ir.draft_build as build
    from tap.agent.mapping_validation import issue
    a,tools,plan=context(root,True); queue,_=scenario_queue(tools,plan);events=[]
    def broken(*args):
        raise FinalValidationError([dict(**issue('STEP_ORDER_MISMATCH','/tasks','조립 오류',action='STOP'),owner='backend',step_id='1-1')])
    monkeypatch.setattr(build,'validate_final_ir',broken)
    with pytest.raises(ValueError,match='백엔드 조립') as error:generate_checked(root,queue,events)
    assert not queue and not list((root/'data/out/scenario_ir_drafts').glob('*.json'))
    assert (root/error.value.log_file).is_file()


def test_final_mapping_repair_shares_step_limit(root, monkeypatch):
    import tap.ir.draft_build as build
    from tap.agent.mapping_validation import issue
    a,tools,plan=context(root,True); queue,proposals=scenario_queue(tools,plan);events=[]
    queue.append(api_response(content=json.dumps(proposals['1-1'])))
    original=validate_final_ir; calls=[]
    def once(ir,tools,plan):
        calls.append(1)
        if len(calls)==1:
            raise FinalValidationError([dict(**issue('EVIDENCE_MISMATCH','/inputs/0','작성안 재검사'),owner='mapping',step_id='1-1')])
        return original(ir,tools,plan)
    monkeypatch.setattr(build,'validate_final_ir',once)
    result=generate_checked(root,queue,events)
    assert len(calls)==2 and not queue
    repair=next(e for e in events if e['event']=='mapping_repair')
    assert repair['request']['phase']=='final_ir' and repair['result']['repair_remaining']==0
    assert result['ir']['generation']['usage']['llm_calls']==10


def test_rejected_mode_is_logged_before_llm_creation(root):
    def forbidden(*args):raise AssertionError('LLM must not be created')
    with pytest.raises(ValueError,match='생성 모드') as error:
        generate(root,FILENAME,runtime_factory=forbidden,generation_mode='bad')
    assert (root/error.value.log_file).is_file()
    assert not list((root/'data/out/scenario_ir_drafts').glob('*.json'))


def test_final_gate_cannot_grant_second_repair(root, monkeypatch):
    import tap.ir.draft_build as build
    from tap.agent.mapping_validation import issue
    a,tools,plan=context(root,True);queue,proposals=scenario_queue(tools,plan);events=[]
    bad=deepcopy(proposals['1-1']);bad['inputs'][0]['value']=1442
    queue[2]=api_response(content=json.dumps(bad))
    queue.insert(3,api_response(content=json.dumps(proposals['1-1'])))
    def broken(*args):
        raise FinalValidationError([dict(**issue('VALUE_TYPE_MISMATCH','/inputs/0','재검사 오류'),owner='mapping',step_id='1-1')])
    monkeypatch.setattr(build,'validate_final_ir',broken)
    with pytest.raises(ValueError,match='수정 기회'):generate_checked(root,queue,events)
    assert not queue
    assert sum(e['event']=='mapping_repair' for e in events)==1
    assert not list((root/'data/out/scenario_ir_drafts').glob('*.json'))


def test_upstream_repair_revalidates_consumers(root, monkeypatch):
    import tap.ir.draft_build as build
    a,tools,plan=context(root,True);queue,proposals=scenario_queue(tools,plan);events=[]
    queue.append(api_response(content=json.dumps(proposals['1-1'])))
    original=validate_final_ir; calls=[]; first_errors=[]
    def corrupt_once(ir,tools,plan):
        calls.append(1)
        if len(calls)==1:ir['tasks'][0]['steps'][0]['outputs'][0]['row_scope']='/incorrect_scope'
        try:return original(ir,tools,plan)
        except FinalValidationError as error:
            first_errors.extend(error.errors);raise
    monkeypatch.setattr(build,'validate_final_ir',corrupt_once)
    result=generate_checked(root,queue,events)
    assert len(calls)==2 and not queue
    assert {'1-1','2-1','2-2','2-3'} <= {e['step_id'] for e in first_errors}
    assert result['ir']['tasks'][1]['steps'][0]['bindings'][0]['from']['row_scope'] != '/incorrect_scope'


def test_retry_after_is_honored_and_quota_is_terminal():
    from openai import RateLimitError
    from tap.agent.llm_retry import retry_delay
    response=httpx.Response(429,request=httpx.Request('POST','https://api.openai.com/v1/responses'),headers={'retry-after':'2.5'})
    error=RateLimitError('rate limit',response=response,body={'code':'rate_limit_exceeded'})
    assert retry_delay(error,harness_configuration(generation_mode='validated'),0)==2.5
    quota=RateLimitError('quota',response=response,body={'code':'insufficient_quota'})
    assert retry_delay(quota,harness_configuration(generation_mode='validated'),0) is None


def test_optional_corruption_is_not_a_failure_until_needed(root):
    a,tools,plan=context(root)
    for file in (root/'data/out/parameters/response_outputs').rglob('*.json'):
        file.write_text('{broken')
    tools=ParameterTools(root,a,defer_optional_errors=True)
    assert tools.read('get_parameter_knowledge',plan[0]['selected_api_id'])['data']
    assert tools.validate(empty_proposal(plan[0]),plan[0],{})['valid']
    from tap.agent.parameter_tools import MaterialError
    with pytest.raises(MaterialError):tools.read('get_response_outputs',plan[0]['selected_api_id'])


def test_malformed_required_artifact_is_not_a_model_repair(root):
    a,tools,plan=context(root);current=plan[0]
    document,_=tools.records['get_parameter_knowledge',current['selected_api_id']]
    document['parameters']=None
    runtime,requests,events=queued_runtime(tools,[api_response(read_calls(tools,current))])
    with pytest.raises(ValueError,match='자료 오류'):
        runtime.run(current,{},a['intent_tasks'][0],a['original_question'],[])
    assert len(requests)==1 and runtime.repair_counts=={}
    assert next(e for e in events if e['event']=='tool_result')['result']['fatal'] is True


@pytest.mark.parametrize('stream',[False,True])
def test_server_mode_contract_json_and_ndjson(root, monkeypatch, stream):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.request import Request,urlopen
    import tap.ir.draft_build as build
    from tap.ui.serve import make_handler
    a,tools,plan=context(root,True);queue,_=scenario_queue(tools,plan)
    original=build.generate
    def run(r,f,c,**kwargs):
        return original(r,f,c,runtime_factory=lambda tools,config:queued_runtime(tools,queue)[0],**kwargs)
    monkeypatch.setattr(build,'generate',run)
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(root))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(url+'/api/approved-selections') as response: defaults=json.load(response)
        assert defaults['default_generation_mode']=='basic'
        assert {m['value'] for m in defaults['generation_modes']}=={'basic','validated'}
        body=json.dumps(dict(approved_filename=FILENAME,generation_mode='validated')).encode()
        headers={'Content-Type':'application/json','Accept':'application/x-ndjson' if stream else 'application/json'}
        with urlopen(Request(url+'/api/scenario-ir-drafts',data=body,headers=headers)) as response:
            raw=response.read().decode()
        if stream:
            events=[json.loads(line) for line in raw.splitlines()]
            assert events[0]['execution_mode']=='validated'
            result=events[-1]['result']
            assert any(e['event']=='final_ir_validation' and e['result']['valid'] for e in events)
        else:result=json.loads(raw)
        assert result['ir']['generation']['execution_mode']=='validated'
        assert not queue
    finally:
        server.shutdown();server.server_close();thread.join()


def test_assertions_are_outside_mapping_validation_scope(root):
    _,tools,plan=context(root)
    c=fixed_candidate(tools,plan[0]);c['assertions']=[{'name':'excluded'}]
    assert tools.validate(c,plan[0],{})['valid']
