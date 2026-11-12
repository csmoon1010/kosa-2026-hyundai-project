"""Exercise real artifacts and the runtime without paid model/business API calls."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from tap.agent.parameter_tools import ParameterTools
from tap.agent.config import configuration
from tap.agent.runtime import Runtime
from openai.types.responses import Response
from tap.ir.draft_build import generate, fixed_plan, approved_path

PROJECT = Path(__file__).resolve().parents[1]
FILENAME = 'api-selection-approved-order-shipment.json'


@pytest.fixture
def root(tmp_path):
    shutil.copytree(PROJECT / 'prototype/approved', tmp_path / 'prototype/approved')
    shutil.copytree(PROJECT / 'data/out/parameters', tmp_path / 'data/out/parameters')
    return tmp_path


def candidate(tools, current, previous):
    inputs = []
    for f in tools.schema(current['selected_api_id'])['parameters']:
        inputs.append(dict(field=f['name'],parameter_path=f['path'],xml_path=f.get('xmlPath'),type=f['type'],source='unresolved',origin='unresolved',value=None,ref=None,reason='업무 값 확인 필요',evidence=[]))
    return dict(step_id=current['step_id'],inputs=inputs,outputs=[],bindings=[],assertions=[],unresolved=[])


def unit_plan(approved):
    """No result dependency: isolate the generic KB/optional-tool contract."""
    plan=fixed_plan(approved)
    for step in plan:
        step['input_dependencies']=[]
        step['output_consumers']=[]
    return plan


def api_response(output=None, content=None, status='completed', reason=None, tokens=(8, 2)):
    output = list(output or [])
    if content is not None:
        output.append(dict(type='message', id='msg-1', role='assistant', status='completed',
                           content=[dict(type='output_text', text=content, annotations=[])]))
    return Response.model_validate(dict(id='resp-test', created_at=1, object='response', model='test',
        output=output, status=status, parallel_tool_calls=True, tool_choice='auto', tools=[],
        incomplete_details={'reason': reason} if reason else None,
        usage=dict(input_tokens=tokens[0], output_tokens=tokens[1], total_tokens=sum(tokens),
                   input_tokens_details={'cached_tokens': 0, 'cache_write_tokens': 0}, output_tokens_details={'reasoning_tokens': 0})))


def read_calls(tools, current):
    return [dict(type='function_call', id=f'fc-{i}', call_id=f'call-{i}', name=name,
                 arguments=json.dumps({'selected_api_id': current['selected_api_id']}), status='completed')
            for i, name in enumerate(['get_parameter_knowledge'])]


class FakeRuntime:
    def __init__(self, tools, config):
        self.tools=tools
        self.usage=dict(llm_calls=0,input_tokens=0,output_tokens=0,total_tokens=0,elapsed_seconds=0)
        self.trace=[]

    def run(self,current,previous,*args):
        self.usage['llm_calls']+=1
        return candidate(self.tools,current,previous)


def test_fixed_plan_and_saved_draft(root):
    result=generate(root,FILENAME,{'max_turns':20},runtime_factory=FakeRuntime)
    ir=result['ir']
    assert ir == json.loads((root/result['file']).read_text())
    assert [len(t['steps']) for t in ir['tasks']]==[1,3]
    assert [s['step_id'] for t in ir['tasks'] for s in t['steps']]==['1-1','2-1','2-2','2-3']
    assert ir['status']=='needs_input'
    assert ir['unresolved'][0]['reason']==json.loads((root/'prototype/approved'/FILENAME).read_text())['unresolved'][0]['reason']
    assert ir['generation']['config']['max_turns']==20
    assert not (root/'data/scenarios').exists()
    assert not any(k in ir for k in ['execution_policy','approvals'])
    again=generate(root,FILENAME,runtime_factory=FakeRuntime)
    assert result['file']!=again['file']


def test_sparse_baseline_replacements_ignore_required_metadata(root):
    class Replacements(FakeRuntime):
        def run(self,current,previous,*args):
            r=super().run(current,previous)
            r['inputs']=[dict(field='venCd',parameter_path='$.body.data1.data2.data3.venCd',source='fixed',origin='user_condition',value='001442',reason='사용자 협력사 코드로 대체')]
            return r
    baseline=next((root/'data/out/parameters/baseline').rglob('*selectOshpDtlList*.json'))
    before=baseline.read_bytes()
    result=generate(root,FILENAME,runtime_factory=Replacements)
    step=result['ir']['tasks'][0]['steps'][0]
    assert len(step['inputs'])==1  # no headers or missing/required fields forced into the proposal
    x=step['inputs'][0]
    assert x['value']=='001442' and x['baseline_value']=='003766'
    assert x['change_kind']=='replace'
    assert result['ir']['generation']['validation']['required_fields'] is False
    assert baseline.read_bytes()==before
    assert result['step_previews']['1-1']['available'] is True
    assert '<venCd>001442</venCd>' in result['step_previews']['1-1']['applied_xml']
    assert 'step_previews' not in result['ir']


def test_validator_paths_types_references_and_evidence(root):
    approved=json.loads((root/'prototype/approved'/FILENAME).read_text())
    current=unit_plan(approved)[0]
    tools=ParameterTools(root,approved)
    c=candidate(tools,current,{})
    assert tools.validate(c,current,{})['valid']
    ven=next(x for x in c['inputs'] if x['field']=='venCd')
    ven.update(source='fixed',origin='user_condition',value=1442,evidence=[dict(source_id='approved',source_pointer='/original_question',quote='001442')])
    assert not tools.validate(c,current,{})['valid']
    ven['value']='001442'
    assert tools.validate(c,current,{})['valid']
    ven['evidence'][0]['quote']='not in source'
    assert not tools.validate(c,current,{})['valid']
    ven.update(source='bind',value=None,ref='missing',evidence=[])
    assert not tools.validate(c,current,{})['valid']


def test_settings_and_input_identity(root):
    with pytest.raises(ValueError): configuration({'max_turns':True})
    with pytest.raises(ValueError): configuration({'max_tokens':1})
    with pytest.raises(ValueError): approved_path(root,'../secret.json')
    a=json.loads((root/'prototype/approved'/FILENAME).read_text())
    a['api_selection_results'][0]['domain']='PD'
    with pytest.raises(ValueError): fixed_plan(a)


def test_config_snapshot_and_numeric_api_contract():
    from tap.agent.config import CONFIG, DEFAULTS, harness_configuration
    first = harness_configuration({'max_turns': 27})
    second = harness_configuration()
    first['errors']['budget'] = 'changed'
    first['text']['format']['type'] = 'changed'
    assert second['errors']['budget'] == CONFIG['errors']['budget']
    assert second['text']['format']['type'] == 'json_schema'
    assert second['text']['format']['strict'] is True
    assert second['store'] is False
    assert first['max_turns'] == 27 and second['max_turns'] == DEFAULTS['max_turns']
    assert set(configuration()) == set(DEFAULTS)
    for values in ([], 'bad', {'instructions': 'user override'}, {'max_seconds': 0}):
        with pytest.raises(ValueError): configuration(values)


def test_registry_definitions_and_error_configuration(root):
    from tap.agent.config import harness_configuration
    from tap.agent.tool_registry import ToolRegistry
    a = json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools = ParameterTools(root, a)
    errors = harness_configuration()['errors']
    errors.update(tool='도구 실패: {e}', unknown_tool='등록되지 않은 도구')
    registry = ToolRegistry(tools, unit_plan(a)[0], {}, errors)
    assert {x['name'] for x in registry.specs} == {'get_parameter_knowledge'}
    registry.call_tool('get_parameter_knowledge', json.dumps({'selected_api_id': unit_plan(a)[0]['selected_api_id']}))
    assert {x['name'] for x in registry.specs} == {'get_parameter_knowledge','get_baseline_request','get_response_outputs'}
    assert registry.call_tool('unknown', '{}') == {'error': '도구 실패: 등록되지 않은 도구'}
    assert 'error' in registry.call_tool('get_request_schema', '[]')
    assert 'error' in registry.call_tool('validate_mapping', '{broken')
    assert registry.finish('[]')[0] is None
    registry.specs.clear()
    assert len(ToolRegistry(tools, unit_plan(a)[0], {}, errors).specs) == 1


def test_runtime_reads_instructions_and_errors_from_config(root, monkeypatch):
    from tap.agent.config import CONFIG
    a = json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools = ParameterTools(root, a)
    current = unit_plan(a)[0]
    monkeypatch.setitem(CONFIG, 'instructions', '테스트 지시문')
    monkeypatch.setitem(CONFIG, 'errors', {**CONFIG['errors'], 'output_length': '출력 설정 확인'})
    def create(**kwargs):
        assert kwargs['instructions'] == '테스트 지시문'
        assert len(kwargs['tools']) == 1
        assert kwargs['tool_choice'] == {'type':'function','name':'get_parameter_knowledge'}
        assert kwargs['max_output_tokens'] == 1024
        assert kwargs['store'] is False
        assert kwargs['text']['format']['type'] == 'json_schema'
        assert 0 < kwargs['timeout'] <= 30
        return api_response(status='incomplete', reason='max_output_tokens')
    runtime = Runtime(tools, {'max_output_tokens': 1024, 'max_seconds': 30},
                      client=NS(responses=NS(create=create)), model='test')
    with pytest.raises(ValueError, match='출력 설정 확인'):
        runtime.run(current, {}, a['intent_tasks'][0], a['original_question'], [])


def test_harness_returns_analysis_after_reads_without_validator(root):
    a=json.loads((root/'prototype/approved'/FILENAME).read_text())
    current=unit_plan(a)[0]; tools=ParameterTools(root,a)
    c=candidate(tools,current,{})
    reasoning=dict(type='reasoning', id='rs-1', summary=[], encrypted_content='opaque-context')
    calls=read_calls(tools,current)
    queue=[api_response([reasoning, *calls], tokens=(10,5)), api_response(content=json.dumps(c), tokens=(10,5))]
    requests=[]
    def create(**kw):
        requests.append(json.loads(json.dumps(kw)))
        return queue.pop(0)
    runtime=Runtime(tools,configuration({'max_turns':2}),client=NS(responses=NS(create=create)),model='test')
    assert runtime.run(current,{},a['intent_tasks'][0],a['original_question'],[])==c
    assert runtime.usage['total_tokens']==30
    assert runtime.usage['llm_calls']==2
    assert not queue
    assert all(e['tool']!='validate_mapping' for e in runtime.trace)
    replay=requests[1]['input']
    assert replay[1]['type']=='reasoning' and replay[1]['encrypted_content']=='opaque-context'
    outputs=[x for x in replay if x.get('type')=='function_call_output']
    assert [x['call_id'] for x in outputs]==[x['call_id'] for x in calls]
    assert all('data' in json.loads(x['output']) for x in outputs)
    assert len(requests[0]['input'])==1
    assert requests[0]['instructions']==requests[1]['instructions']
    assert requests[0]['tool_choice']=={'type':'function','name':'get_parameter_knowledge'}
    assert requests[1]['tool_choice']=='auto'
    assert len(requests[1]['tools'])==3


def test_harness_exhaustion(root):
    a=json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools=ParameterTools(root,a); current=unit_plan(a)[0]
    def create(**kw): return api_response(content='{}',tokens=(1,1))
    r=Runtime(tools,configuration({'max_turns':1}),client=NS(responses=NS(create=create)),model='test')
    with pytest.raises(ValueError,match='RUN_LLM_LIMIT'): r.run(current,{},a['intent_tasks'][0],a['original_question'],[])


def test_http_list_generate_and_save(root, monkeypatch):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.request import Request, urlopen
    from tap.ui.serve import make_handler
    from tap.ir import draft_build
    original=draft_build.generate
    monkeypatch.setattr(draft_build,'generate',lambda r,f,c:original(r,f,c,runtime_factory=FakeRuntime))
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(root))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(url+'/api/approved-selections') as response: listing=json.load(response)
        assert any(x['filename']==FILENAME for x in listing['files'])
        assert listing['defaults']['max_turns']==16
        req=Request(url+'/api/scenario-ir-drafts',data=json.dumps(dict(approved_filename=FILENAME,generation_config={'max_turns':24})).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req) as response: result=json.load(response)
        assert result['ir']['generation']['config']['max_turns']==24
        assert (root/result['file']).is_file()
    finally:
        server.shutdown();server.server_close();thread.join()


def test_progress_snapshots_redact_credentials(monkeypatch):
    from tap.agent.progress import snapshot
    monkeypatch.setenv('OPENAI_API_KEY', 'test-secret-value-unique')
    value = {'messages': [{'content': json.dumps({'field':'oauseKey','value':'private-header'})}],
             'error':'failed test-secret-value-unique', 'usage':{'total_tokens':123}}
    cleaned = snapshot(value)
    assert 'private-header' not in json.dumps(cleaned)
    assert 'test-secret-value-unique' not in json.dumps(cleaned)
    assert cleaned['usage']['total_tokens'] == 123
    assert 'private-header' in value['messages'][0]['content']  # original model input unchanged


def test_runtime_progress_includes_prompt_usage_and_tool_events(root):
    a=json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools=ParameterTools(root,a);current=unit_plan(a)[0]; c=candidate(tools,current,{})
    queue=[api_response(read_calls(tools,current)),api_response(content=json.dumps(c))]
    def create(**kw): return queue.pop(0)
    r=Runtime(tools,configuration(),client=NS(responses=NS(create=create)),model='test')
    events=[];r.on_event=events.append
    assert r.run(current,{},a['intent_tasks'][0],a['original_question'],[])==c
    assert events[0]['event']=='llm_request' and events[0]['next_turn']==1
    assert events[0]['instructions']
    assert events[0]['input'][0]['role']=='user'
    assert len(events[0]['input'])==1
    assert events[0]['text']['format']['strict'] is True
    responses=[e for e in events if e['event']=='llm_response']
    assert responses[-1]['usage']['total_tokens']==20
    assert responses[-1]['response_status']=='completed'
    assert responses[-1]['output']['object']=='response'
    assert r.usage['llm_calls']==2
    assert responses[-1]['turn_usage']['total_tokens']==10
    selected=[e for e in events if e['event']=='tool_selected']
    assert len(selected)==1
    assert events[-1]['event']=='step_complete'
    assert all('elapsed_seconds' in e for e in events)


def test_http_stream_flushes_start_and_retains_failure(root, monkeypatch):
    from http.server import ThreadingHTTPServer
    from threading import Thread, Event
    from urllib.request import Request, urlopen
    from tap.ui.serve import make_handler
    from tap.ir import draft_build
    release=Event()
    def generate(r,f,c,on_event=None):
        on_event({'event':'generation_start'})
        on_event({'event':'tool_start','tool':'get_request_schema','turn':1})
        assert release.wait(3)
        raise ValueError('진행 중 실패')
    monkeypatch.setattr(draft_build,'generate',generate)
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(root))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        req=Request(f'http://127.0.0.1:{server.server_port}/api/scenario-ir-drafts',data=json.dumps({'approved_filename':FILENAME}).encode(),headers={'Content-Type':'application/json','Accept':'application/x-ndjson'})
        with urlopen(req,timeout=3) as response:
            assert response.headers.get_content_type()=='application/x-ndjson'
            assert json.loads(response.readline())['event']=='generation_start'
            assert json.loads(response.readline())['event']=='tool_start'
            release.set()
            failure=json.loads(response.readline())
            assert failure['event']=='generation_error' and failure['error']=='진행 중 실패'
    finally:
        release.set();server.shutdown();server.server_close();thread.join()


def test_http_stream_success_still_saves_draft(root,monkeypatch):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.request import Request,urlopen
    from tap.ui.serve import make_handler
    from tap.ir import draft_build
    original=draft_build.generate
    monkeypatch.setattr(draft_build,'generate',lambda r,f,c,on_event=None:original(r,f,c,runtime_factory=FakeRuntime,on_event=on_event))
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(root))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        req=Request(f'http://127.0.0.1:{server.server_port}/api/scenario-ir-drafts',data=json.dumps({'approved_filename':FILENAME}).encode(),headers={'Content-Type':'application/json','Accept':'application/x-ndjson'})
        with urlopen(req,timeout=3) as response: events=[json.loads(line) for line in response]
        assert events[0]['event']=='generation_start' and events[-1]['event']=='generation_complete'
        assert sum(e['event']=='backend_canonical' for e in events)==4
        assert sum(e['event']=='backend_baseline_compare' for e in events)==4
        assert sum(e['event']=='step_preview' for e in events)==4
        result=events[-1]['result']
        assert json.loads((root/result['file']).read_text())==result['ir']
    finally:
        server.shutdown();server.server_close();thread.join()


def test_analysis_acceptance_needs_reads_but_not_validator(root):
    from tap.agent.config import harness_configuration
    from tap.agent.tool_registry import ToolRegistry
    a=json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools=ParameterTools(root,a);current=unit_plan(a)[0]
    registry=ToolRegistry(tools,current,{},harness_configuration()['errors'])
    c=dict(step_id=current['step_id'],inputs=[],outputs=[],bindings=[],assertions=[],unresolved=[])
    assert registry.finish(json.dumps(c))[0] is None
    assert '비활성화' in registry.call_tool('validate_mapping','{}')['error']
    for name in ['get_parameter_knowledge']:
        registry.call_tool(name,json.dumps({'selected_api_id':current['selected_api_id']}))
    adopted,feedback=registry.finish(json.dumps(c))
    assert adopted['inputs']==[] and feedback is None
    assert adopted['assertions']==[]


def test_analysis_skips_mapping_validators(root,monkeypatch):
    from tap.ir import draft_build
    def forbidden(*args,**kwargs):
        raise AssertionError('매핑 검증은 현재 비활성화되어야 합니다')
    monkeypatch.setattr(draft_build,'validate_final_ir',forbidden)
    monkeypatch.setattr(ParameterTools,'validate',forbidden)
    result=generate(root,FILENAME,runtime_factory=FakeRuntime)
    assert (root/result['file']).exists()
    assert result['ir']['generation']['mode']=='baseline_replacements'
    assert result['ir']['generation']['validation']==dict(mapping=False,required_fields=False,final_mapping=False)


def test_full_generation_journal_and_ir_link(root,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','unique-journal-secret')
    class Logged(FakeRuntime):
        def run(self,current,previous,*args):
            self.on_event(dict(event='llm_request',step_id=current['step_id'],turn=1,
                               messages=[{'content':'unique-journal-secret'}]))
            self.on_event(dict(event='tool_result',tool='validate_mapping',result={'valid':True},usage=self.usage))
            return super().run(current,previous,*args)
    result=generate(root,FILENAME,runtime_factory=Logged)
    text=(root/result['log_file']).read_text()
    events=[json.loads(line) for line in text.splitlines()]
    assert events[0]['event']=='generation_start'
    assert events[-1]['event']=='generation_complete'
    assert any(e['event']=='llm_request' for e in events)
    assert any(e.get('result',{}).get('valid') is True for e in events)
    assert [e['sequence'] for e in events]==list(range(1,len(events)+1))
    assert len({e['run_id'] for e in events})==1
    assert 'unique-journal-secret' not in text
    assert result['ir']['generation']['log_file']==result['log_file']
    assert json.loads((root/result['file']).read_text())['generation']['log_file']==result['log_file']
    assert result['log_file']!=generate(root,FILENAME,runtime_factory=FakeRuntime)['log_file']


def test_failed_generation_journal_is_flushed_and_closed(root):
    class Broken(FakeRuntime):
        def run(self,current,*args):
            self.on_event({'event':'tool_start','step_id':current['step_id'],'tool':'get_request_schema'})
            raise ValueError('의도한 오류')
    with pytest.raises(ValueError,match='의도한 오류') as caught:
        generate(root,FILENAME,runtime_factory=Broken)
    file=root/caught.value.log_file
    events=[json.loads(line) for line in file.read_text().splitlines()]
    assert [e['event'] for e in events]==['generation_start','budget_initialized','scenario_steps','backend_canonical','tool_start','generation_error']
    assert '의도한 오류' in events[-1]['traceback']
    assert not (root/'data/out/scenario_ir_drafts').exists()


def test_log_download_for_failed_http_generation(root):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    from tap.ui.serve import make_handler
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(root))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        req=Request(base+'/api/scenario-ir-drafts',data=json.dumps({'approved_filename':'missing.json'}).encode(),headers={'Content-Type':'application/json'})
        with pytest.raises(HTTPError) as caught: urlopen(req,timeout=3)
        error=json.load(caught.value)
        assert error['log_file']
        with urlopen(base+error['log_url']) as response:
            assert response.headers['Content-Disposition'].startswith('attachment;')
            raw=response.read()
        assert raw==(root/error['log_file']).read_bytes()
        events=[json.loads(x) for x in raw.decode().splitlines()]
        assert events[-1]['event']=='generation_error'
        with pytest.raises(HTTPError): urlopen(base+'/api/scenario-ir-logs/not-a-log.jsonl')
    finally:
        server.shutdown();server.server_close();thread.join()


def test_per_step_baseline_comparison_and_response_binding(root):
    row='/Response2XML/Dataset[@id="dsOutput"]/rows/row'
    class PerStep(FakeRuntime):
        def run(self,current,previous,*args):
            path='$.body.data1.data2.data3.'
            r=dict(step_id=current['step_id'],inputs=[],outputs=[],bindings=[],assertions=[],unresolved=[])
            if current['step_id']=='1-1':
                r['inputs']=[dict(field='venCd',parameter_path=path+'venCd',source='fixed',value='001442')]
                r['outputs']=[dict(name='ordNo',response_key='200',content_type='application/xml',response_path=row+'/ordNo',path_type='XPATH',type='string',row_scope=row)]
            else:
                r['inputs']=[dict(field='procGb',parameter_path=path+'procGb',source='fixed',value='P'+str(current['step'])),dict(field='ordNo',parameter_path=path+'ordNo',source='bind',ref='B-'+current['step_id'],value=None)]
                r['bindings']=[dict(binding_id='B-'+current['step_id'],to_parameter_path=path+'ordNo',**{'from':dict(from_step_id='1-1',output_name='ordNo',response_key='200',content_type='application/xml',response_path=row+'/ordNo',path_type='XPATH',row_scope=row)})]
            return r
    ir=generate(root,FILENAME,runtime_factory=PerStep)['ir']
    steps=ir['tasks'][1]['steps']
    assert [s['inputs'][0]['baseline_value'] for s in steps]==['P1']*3
    assert [s['inputs'][0]['value'] for s in steps]==['P1','P2','P3']
    assert [s['inputs'][0]['change_kind'] for s in steps]==['unchanged','replace','replace']
    assert all(s['inputs'][1]['baseline_value']=='20160118110258' and s['inputs'][1]['change_kind']=='response_binding' for s in steps)
    assert ir['tasks'][1]['depends_on']==[1]
    assert not any('필수' in u['reason'] for u in ir['unresolved'])


@pytest.mark.parametrize('case', ['max_output_tokens', 'content_filter', 'failed', 'refusal'])
def test_responses_terminal_errors_do_not_execute_tools(root, monkeypatch, case):
    a=json.loads((root/'prototype/approved'/FILENAME).read_text())
    current=unit_plan(a)[0]; tools=ParameterTools(root,a)
    def forbidden(*args, **kwargs):
        raise AssertionError('불완전 응답의 도구가 실행됨')
    monkeypatch.setattr(tools, 'read', forbidden)
    output=read_calls(tools,current)
    if case == 'refusal':
        output.append(dict(type='message',id='msg-refusal',role='assistant',status='completed',
                           content=[dict(type='refusal',refusal='처리 불가')]))
        response=api_response(output)
    elif case == 'failed':
        response=api_response(output,status='failed')
        response.usage=None
    else:
        response=api_response(output,status='incomplete',reason=case)
    runtime=Runtime(tools,configuration(),client=NS(responses=NS(create=lambda **kw:response)),model='test')
    events=[];runtime.on_event=events.append
    with pytest.raises(ValueError):
        runtime.run(current,{},a['intent_tasks'][0],a['original_question'],[])
    assert runtime.usage['llm_calls']==1
    assert not runtime.trace
    assert events[-1]['event']=='llm_error'
    assert any(e['event']=='llm_response' for e in events)


def test_sdk_responses_http_contract_and_step_context_reset(root):
    try:
        import httpx2 as httpx
    except ImportError:
        import httpx
    from openai import OpenAI
    a=json.loads((root/'prototype/approved'/FILENAME).read_text())
    plan=unit_plan(a);tools=ParameterTools(root,a)
    proposals=[candidate(tools,current,{}) for current in plan[:2]]
    # Exercise the final typed output, preserving the leading-zero identifier.
    proposals[0]['inputs']=proposals[0]['inputs'][:1]
    proposals[0]['inputs'][0].update(source='fixed',origin='user_condition',value='001442')
    queue=[]
    for current,c in zip(plan,proposals):
        queue.extend([api_response(read_calls(tools,current)),api_response(content=json.dumps(c))])
    bodies=[]
    def handler(request):
        assert request.url.path=='/v1/responses'
        bodies.append(json.loads(request.content))
        assert 'messages' not in bodies[-1] and 'response_format' not in bodies[-1]
        return httpx.Response(200,json=queue.pop(0).model_dump(mode='json'))
    with OpenAI(api_key='dummy-offline-test',http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        runtime=Runtime(tools,configuration(),client=client,model='test')
        first=runtime.run(plan[0],{},a['intent_tasks'][0],a['original_question'],plan[1:])
        prior={**first,'api':{'api_id':plan[0]['selected_api_id']}}
        second=runtime.run(plan[1],{plan[0]['step_id']:prior},a['intent_tasks'][1],a['original_question'],plan[2:])
    assert first==proposals[0] and second==proposals[1]
    assert first['inputs'][0]['value']=='001442'
    assert len(bodies[0]['input'])==len(bodies[2]['input'])==1
    assert json.loads(bodies[2]['input'][0]['content'])['previous_steps']=={plan[0]['step_id']:prior}
    assert bodies[0]['store'] is False
    assert bodies[0]['include']==['reasoning.encrypted_content']
    assert all(t['strict'] and 'function' not in t for t in bodies[0]['tools'])
    schema=bodies[0]['text']['format']
    assert schema['type']=='json_schema' and schema['strict'] is True
    assert schema['schema']['additionalProperties'] is False
    assert runtime.usage['llm_calls']==4 and runtime.usage['total_tokens']==40


@pytest.fixture
def material_context(root):
    from tap.agent.config import harness_configuration
    from tap.agent.tool_registry import ToolRegistry
    approved=json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools=ParameterTools(root,approved);plan=unit_plan(approved)
    registry=ToolRegistry(tools,plan[0],{},harness_configuration()['errors'])
    return approved,tools,plan,registry


def empty_proposal(current):
    return dict(step_id=current['step_id'],inputs=[],outputs=[],bindings=[],assertions=[],unresolved=[])


def test_kb_schema_and_canonical_fallback_provenance(material_context):
    _,tools,plan,_=material_context
    api=plan[0]['selected_api_id']
    document,kb_source=tools.records['get_parameter_knowledge',api]
    field=document['parameters'][0]
    field['schema'].pop('type')
    kb=tools.read('get_parameter_knowledge',api)
    supplied=kb['data']['parameters'][0]
    assert supplied['schema']['type']
    assert supplied['schema']['xml_path']==field['schema']['xml_path']
    assert supplied['schema_sources']['type']['source_id']!=kb_source
    assert supplied['schema_sources']['xml_path']['source_id']==kb_source
    assert supplied['schema_sources']['type']['source_id'] in tools.used_source_ids
    assert supplied['provenance']==field['provenance']
    assert supplied['knowledge']==field['knowledge']


def test_material_dependencies_only_require_requested_data(material_context):
    _,tools,plan,registry=material_context
    api=plan[0]['selected_api_id'];c=empty_proposal(plan[0])
    assert registry.finish(json.dumps(c))[1]['needed_tools']==['get_parameter_knowledge']
    registry.call_tool('get_parameter_knowledge',json.dumps({'selected_api_id':api}))
    assert registry.finish(json.dumps(c))==(c,None)
    # Backend access is not a model-delivered Baseline.
    baseline=tools.read('get_baseline_request',api)
    c['inputs']=candidate(tools,plan[0],{})['inputs'][:1]
    c['inputs'][0]['evidence']=[dict(source_id=baseline['source_id'],source_pointer='/parameters/0',quote='value')]
    assert registry.finish(json.dumps(c))[1]['needed_materials']==[dict(tool='get_baseline_request',selected_api_id=api)]
    registry.call_tool('get_baseline_request',json.dumps({'selected_api_id':api}))
    assert registry.finish(json.dumps(c))==(c,None)
    foreign=next(x['source_id'] for x in tools.sources if x['kind']=='baseline' and x['selected_api_id']!=api)
    c['inputs'][0]['evidence'][0]['source_id']=foreign
    # Do not ask for an out-of-scope Baseline that the model cannot call.
    rejected,feedback=registry.finish(json.dumps(c))
    assert rejected is None and 'needed_materials' not in feedback


def output_definition(tools, api):
    data=tools.read('get_response_outputs',api)['data']['outputs']
    field=next(x for x in data if x['name']=='ordNo')
    return {**{k:field[k] for k in ['name','response_key','content_type','response_path','path_type','type']},
            'row_scope':field['response_path'].rsplit('/',1)[0], 'evidence':[]}


def test_response_output_dependency_and_previous_binding(material_context):
    from tap.agent.config import harness_configuration
    from tap.agent.tool_registry import ToolRegistry
    _,tools,plan,registry=material_context
    api=plan[0]['selected_api_id'];out=output_definition(tools,api)
    c=empty_proposal(plan[0]);c['outputs']=[out]
    registry.call_tool('get_parameter_knowledge',json.dumps({'selected_api_id':api}))
    assert registry.finish(json.dumps(c))[1]['needed_materials']==[dict(tool='get_response_outputs',selected_api_id=api)]
    registry.call_tool('get_response_outputs',json.dumps({'selected_api_id':api}))
    assert registry.finish(json.dumps(c))==(c,None)
    prior={plan[0]['step_id']:{'api':{'api_id':api},'outputs':[out]}}
    next_registry=ToolRegistry(tools,plan[1],prior,harness_configuration()['errors'])
    next_registry.call_tool('get_parameter_knowledge',json.dumps({'selected_api_id':plan[1]['selected_api_id']}))
    ord_path=next(f['path'] for f in tools.schema(plan[1]['selected_api_id'])['parameters'] if f['path'].endswith('.ordNo'))
    c=empty_proposal(plan[1]);c['bindings']=[dict(binding_id='b1',to_parameter_path=ord_path,**{'from':{
        'from_step_id':plan[0]['step_id'],'output_name':out['name'],
        **{k:out[k] for k in ['response_key','content_type','response_path','path_type','row_scope']}}})]
    assert next_registry.finish(json.dumps(c))==(c,None)
    prior[plan[0]['step_id']]['outputs']=[]
    assert next_registry.finish(json.dumps(c))[1]['needed_materials']==[dict(tool='get_response_outputs',selected_api_id=api)]
    next_registry.call_tool('get_response_outputs',json.dumps({'selected_api_id':api}))
    assert next_registry.finish(json.dumps(c))==(c,None)
    patches=next_registry.apply_output_patches()
    assert patches[0]['step_id']=='1-1'
    assert prior['1-1']['outputs'][0]['response_path']==out['response_path']
    c['bindings']=[];c['unresolved']=[dict(dependency_ids=[],reason='앞 STEP 출력 미정의',required_input='ordNo 출력 정의',parameter_paths=[],evidence=[])]
    assert next_registry.finish(json.dumps(c))==(c,None)


def test_runtime_adds_only_missing_response_tool(material_context):
    approved,tools,plan,_=material_context
    current=plan[0];c=empty_proposal(current);c['outputs']=[output_definition(tools,current['selected_api_id'])]
    response_call=dict(type='function_call',id='response-call',call_id='response-id',name='get_response_outputs',
                       arguments=json.dumps({'selected_api_id':current['selected_api_id']}),status='completed')
    queue=[api_response(read_calls(tools,current)),api_response(content=json.dumps(c)),
           api_response([response_call]),api_response(content=json.dumps(c))]
    def create(**kw):return queue.pop(0)
    runtime=Runtime(tools,configuration(),client=NS(responses=NS(create=create)),model='test')
    events=[];runtime.on_event=events.append
    assert runtime.run(current,{},approved['intent_tasks'][0],approved['original_question'],[])==c
    assert [x['tool'] for x in runtime.trace]==['get_parameter_knowledge','get_response_outputs']
    feedback=next(e for e in events if e['event']=='validation_feedback')
    assert feedback['result']['needed_materials'][0]['tool']=='get_response_outputs'
    assert runtime.usage['llm_calls']==4


def test_missing_kb_fails_without_retrying_forever(material_context):
    approved,tools,plan,_=material_context
    tools.records.pop(('get_parameter_knowledge',plan[0]['selected_api_id']))
    def create(**kw): return api_response(read_calls(tools,plan[0]))
    runtime=Runtime(tools,configuration(),client=NS(responses=NS(create=create)),model='test')
    with pytest.raises(ValueError,match='자료가 없습니다'):
        runtime.run(plan[0],{},approved['intent_tasks'][0],approved['original_question'],[])
    assert runtime.usage['llm_calls']==1


def test_backend_comparison_missing_and_null_are_distinct(root):
    class Values(FakeRuntime):
        def run(self,current,previous,*args):
            c=empty_proposal(current)
            c['inputs']=[dict(parameter_path='$.headers.oauserId',source='fixed',value=None),
                         dict(parameter_path='$.notInBaseline',source='fixed',value='001442')]
            return c
    ir=generate(root,FILENAME,runtime_factory=Values)['ir']
    first,second=ir['tasks'][0]['steps'][0]['inputs']
    assert first['baseline_present'] is True and first['change_kind']=='unchanged'
    assert second['baseline_present'] is False and second['change_kind']=='comparison_unavailable'
    assert second['comparison_reason']
    shutil.rmtree(root/'data/out/parameters/baseline')
    ir=generate(root,FILENAME,runtime_factory=Values)['ir']
    assert ir['tasks'][0]['steps'][0]['inputs'][0]['change_kind']=='comparison_unavailable'
    assert ir['generation']['tool_policy']=='kb_first_conditional'


def test_generate_uses_real_runtime_with_conditional_tools(root):
    approved=json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools=ParameterTools(root,approved);plan=fixed_plan(approved)
    out=output_definition(tools,plan[0]['selected_api_id'])
    proposals=[];queue=[]
    for current in plan:
        c=empty_proposal(current)
        fields={x['field']:x for x in candidate(tools,current,{})['inputs']}
        if current['step_id']=='1-1':
            fields['venCd'].update(source='fixed',origin='user_condition',value='001442')
            c['inputs']=[fields['venCd']];c['outputs']=[out]
        else:
            fields['procGb'].update(source='fixed',origin='user_condition',value='P'+str(current['step']))
            fields['ordNo'].update(source='bind',origin='previous_output',value=None,ref='b-'+current['step_id'])
            c['inputs']=[fields['procGb'],fields['ordNo']]
            c['bindings']=[dict(binding_id='b-'+current['step_id'],to_parameter_path=fields['ordNo']['parameter_path'],
                **{'from':dict(from_step_id='1-1',output_name='ordNo',**{k:out[k] for k in ['response_key','content_type','response_path','path_type','row_scope']})})]
        queue.append(api_response(read_calls(tools,current)))
        if c['outputs']:
            queue.append(api_response([dict(type='function_call',id='response-1',call_id='response-1',name='get_response_outputs',
                arguments=json.dumps({'selected_api_id':current['selected_api_id']}),status='completed')]))
        queue.append(api_response(content=json.dumps(c)))
        proposals.append(c)
    requests=[]
    def create(**kw):
        requests.append(json.loads(json.dumps(kw)))
        return queue.pop(0)
    client=NS(responses=NS(create=create))
    result=generate(root,FILENAME,runtime_factory=lambda tools,config:Runtime(tools,config,client=client,model='test'))
    assert all('applied_lines' not in json.dumps(request) for request in requests)
    ir=result['ir']
    assert json.loads((root/result['file']).read_text())==ir
    assert ir['generation']['usage']['llm_calls']==9
    assert [s['inputs'][0]['change_kind'] for s in ir['tasks'][1]['steps']]==['unchanged','replace','replace']
    assert ir['tasks'][1]['depends_on']==[1]
    assert len(ir['generation']['trace'])==5
    assert {x['tool'] for x in ir['generation']['trace']}=={'get_parameter_knowledge','get_response_outputs'}
    events=[json.loads(line) for line in (root/result['log_file']).read_text().splitlines()]
    assert sum(e['event']=='backend_baseline_compare' for e in events)==4
    assert sum(e['event']=='material_check' for e in events)==4
    assert sum(e['event']=='tool_selected' for e in events)==5
    assert all(s['assertions']==[] for t in ir['tasks'] for s in t['steps'])
    assert len([x for x in ir['sources']['artifacts'] if x['kind']=='response_outputs'])==1


def test_runtime_baseline_is_optional_but_available(material_context):
    approved,tools,plan,_=material_context
    current=plan[0];c=empty_proposal(current)
    baseline=tools.read('get_baseline_request',current['selected_api_id'])
    field=next(x for x in candidate(tools,current,{})['inputs'] if x['field']=='venCd')
    field.update(source='fixed',origin='user_condition',value='003766',evidence=[
        dict(source_id=baseline['source_id'],source_pointer='/parameters',quote='003766')])
    c['inputs']=[field]
    baseline_call=dict(type='function_call',id='baseline-1',call_id='baseline-1',name='get_baseline_request',
                       arguments=json.dumps({'selected_api_id':current['selected_api_id']}),status='completed')
    queue=[api_response(read_calls(tools,current)),api_response([baseline_call]),api_response(content=json.dumps(c))]
    def create(**kw):return queue.pop(0)
    runtime=Runtime(tools,configuration(),client=NS(responses=NS(create=create)),model='test')
    assert runtime.run(current,{},approved['intent_tasks'][0],approved['original_question'],[])==c
    assert [x['tool'] for x in runtime.trace]==['get_parameter_knowledge','get_baseline_request']
    assert runtime.usage['llm_calls']==3


def test_kb_api_mismatch_is_fatal_and_canonical_is_not_model_tool(material_context):
    _,tools,plan,registry=material_context
    assert 'error' in registry.call_tool('get_request_schema',json.dumps({'selected_api_id':plan[0]['selected_api_id']}))
    document,_=tools.records['get_parameter_knowledge',plan[0]['selected_api_id']]
    document['parameters'][0]['identity']['api_id']='POST:/other'
    result=registry.call_tool('get_parameter_knowledge',json.dumps({'selected_api_id':plan[0]['selected_api_id']}))
    assert result['fatal'] is True and not registry.has_knowledge


def test_fixed_plan_includes_consumer_conditions_and_result_dependencies(root):
    from copy import deepcopy
    approved=json.loads((root/'prototype/approved'/FILENAME).read_text())
    plan=fixed_plan(approved)
    dependency=plan[0]['output_consumers'][0]
    assert dependency['source_step_id']=='1-1' and dependency['consumer_task_sequence']==2
    assert dependency['conditions']==approved['intent_tasks'][1]['conditions']
    assert all(s['input_dependencies'][0]['dependency_id']==dependency['dependency_id'] for s in plan[1:])
    assert plan[1]['intent_task']['conditions']==approved['intent_tasks'][1]['conditions']
    independent=deepcopy(approved);independent['intent_tasks'][1]['conditions']='협력사 설정을 변경한다.'
    assert all(not s['output_consumers'] and not s['input_dependencies'] for s in fixed_plan(independent))
    ambiguous=deepcopy(approved);ambiguous['intent_tasks'][1]['conditions']='9번 업무의 결과를 사용한다.'
    assert fixed_plan(ambiguous)[1]['input_dependencies'][0]['status']=='ambiguous'


def test_log_regression_empty_arrays_cannot_skip_producer_response_read(root):
    approved=json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools=ParameterTools(root,approved);plan=fixed_plan(approved);current=plan[0]
    # Same failure as IRRUN-20261101-153421: KB only, no outputs or bindings.
    omitted=empty_proposal(current)
    repaired=empty_proposal(current);repaired['outputs']=[output_definition(tools,current['selected_api_id'])]
    response_call=dict(type='function_call',id='response-1',call_id='response-1',name='get_response_outputs',
        arguments=json.dumps({'selected_api_id':current['selected_api_id']}),status='completed')
    queue=[api_response(read_calls(tools,current)),api_response(content=json.dumps(omitted)),
           api_response([response_call]),api_response(content=json.dumps(repaired))]
    requests=[]
    def create(**kw):
        requests.append(json.loads(json.dumps(kw)))
        return queue.pop(0)
    runtime=Runtime(tools,configuration(),client=NS(responses=NS(create=create)),model='test')
    events=[];runtime.on_event=events.append
    assert runtime.run(current,{},approved['intent_tasks'][0],approved['original_question'],plan[1:])==repaired
    first=json.loads(requests[0]['input'][0]['content'])
    assert first['following_steps'][0]['intent_task']['conditions']==approved['intent_tasks'][1]['conditions']
    assert first['output_consumers'][0]['source_step_id']=='1-1'
    assert requests[1]['tool_choice']=={'type':'function','name':'get_response_outputs'}
    feedback=next(e['result'] for e in events if e['event']=='validation_feedback')
    assert feedback['needed_materials']==[dict(tool='get_response_outputs',selected_api_id=current['selected_api_id'])]


def test_dependency_unresolved_only_after_response_read_and_scoped_reason(root):
    from tap.agent.config import harness_configuration
    from tap.agent.tool_registry import ToolRegistry
    approved=json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools=ParameterTools(root,approved);current=fixed_plan(approved)[0]
    registry=ToolRegistry(tools,current,{},harness_configuration()['errors'])
    registry.call_tool('get_parameter_knowledge',json.dumps({'selected_api_id':current['selected_api_id']}))
    c=empty_proposal(current)
    c['unresolved']=[dict(dependency_ids=[],reason='前 STEP 출력 없음',required_input='출력 정의',parameter_paths=[],evidence=[])]
    assert 'needed_materials' in registry.finish(json.dumps(c))[1]
    registry.call_tool('get_response_outputs',json.dumps({'selected_api_id':current['selected_api_id']}))
    assert registry.finish(json.dumps(c))[1]['dependencies'][0]['required_action']=='define_outputs'
    c['unresolved'][0]['dependency_ids']=[current['output_consumers'][0]['dependency_id']]
    c['unresolved'][0]['reason']='응답 필드를 확인했으나 소비 업무의 식별 의미가 모호하다'
    assert registry.finish(json.dumps(c))==(c,None)


def test_consumer_queries_missing_source_and_backfills_only_confirmed_output(root):
    from copy import deepcopy
    approved=json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools=ParameterTools(root,approved);plan=fixed_plan(approved);current=plan[1]
    prior={'1-1':dict(api={'api_id':plan[0]['selected_api_id']},inputs=[{'value':'001442'}],outputs=[])}
    original_inputs=deepcopy(prior['1-1']['inputs'])
    omitted=empty_proposal(current)
    omitted['unresolved']=[dict(dependency_ids=[],reason='앞 STEP 출력 없음',required_input='ordNo',parameter_paths=[],evidence=[])]
    out=output_definition(tools,plan[0]['selected_api_id'])
    repaired=empty_proposal(current)
    field=next(x for x in candidate(tools,current,{})['inputs'] if x['field']=='ordNo')
    field.update(source='bind',origin='previous_output',ref='binding-ord',value=None)
    repaired['inputs']=[field]
    repaired['bindings']=[dict(binding_id='binding-ord',to_parameter_path=field['parameter_path'],**{'from':dict(
        from_step_id='1-1',output_name='ordNo',**{k:out[k] for k in ['response_key','content_type','response_path','path_type','row_scope']})})]
    response_call=dict(type='function_call',id='response-1',call_id='response-1',name='get_response_outputs',
        arguments=json.dumps({'selected_api_id':plan[0]['selected_api_id']}),status='completed')
    queue=[api_response(read_calls(tools,current)),api_response(content=json.dumps(omitted)),
           api_response([response_call]),api_response(content=json.dumps(repaired))]
    def create(**kw):return queue.pop(0)
    runtime=Runtime(tools,configuration(),client=NS(responses=NS(create=create)),model='test')
    events=[];runtime.on_event=events.append
    assert runtime.run(current,prior,approved['intent_tasks'][1],approved['original_question'],plan[2:])==repaired
    assert prior['1-1']['inputs']==original_inputs
    assert prior['1-1']['outputs'][0]['response_path']==out['response_path']
    assert any(e['event']=='backend_output_defined' for e in events)
    assert [x['tool'] for x in runtime.trace]==['get_parameter_knowledge','get_response_outputs']


def test_existing_outputs_need_used_binding_without_extra_response_read(root):
    from tap.agent.config import harness_configuration
    from tap.agent.tool_registry import ToolRegistry
    approved=json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools=ParameterTools(root,approved);plan=fixed_plan(approved);current=plan[1]
    out=output_definition(tools,plan[0]['selected_api_id'])
    previous={'1-1':{'api':{'api_id':plan[0]['selected_api_id']},'outputs':[out]}}
    registry=ToolRegistry(tools,current,previous,harness_configuration()['errors'])
    registry.call_tool('get_parameter_knowledge',json.dumps({'selected_api_id':current['selected_api_id']}))
    assert registry.tool_choice=='auto'
    c=empty_proposal(current)
    ord_path=next(f['path'] for f in tools.schema(current['selected_api_id'])['parameters'] if f['path'].endswith('.ordNo'))
    c['bindings']=[dict(binding_id='binding-1',to_parameter_path=ord_path,**{'from':dict(
        from_step_id='1-1',output_name='ordNo',**{k:out[k] for k in ['response_key','content_type','response_path','path_type','row_scope']})})]
    assert registry.finish(json.dumps(c))[1]['dependencies'][0]['required_action']=='define_binding'
    field=next(x for x in candidate(tools,current,{})['inputs'] if x['field']=='ordNo')
    field.update(parameter_path=ord_path,source='bind',origin='previous_output',value=None,ref='binding-1')
    c['inputs']=[field]
    assert registry.finish(json.dumps(c))==(c,None)
    assert {name for name,api in registry.results}=={'get_parameter_knowledge'}


def test_unconfirmed_upstream_output_cannot_patch_previous(material_context):
    from tap.agent.config import harness_configuration
    from tap.agent.tool_registry import ToolRegistry
    _,tools,plan,_=material_context
    out=output_definition(tools,plan[0]['selected_api_id'])
    previous={'1-1':{'api':{'api_id':plan[0]['selected_api_id']},'outputs':[]}}
    registry=ToolRegistry(tools,plan[1],previous,harness_configuration()['errors'])
    registry.call_tool('get_parameter_knowledge',json.dumps({'selected_api_id':plan[1]['selected_api_id']}))
    registry.call_tool('get_response_outputs',json.dumps({'selected_api_id':plan[0]['selected_api_id']}))
    c=empty_proposal(plan[1])
    c['bindings']=[dict(binding_id='bad',to_parameter_path='$.ordNo',**{'from':dict(
        from_step_id='1-1',output_name='invented',**{k:out[k] for k in ['response_key','content_type','response_path','path_type','row_scope']})})]
    c['bindings'][0]['from']['response_path']='/invented'
    assert registry.finish(json.dumps(c))[0] is None
    assert registry.output_patches==[] and previous['1-1']['outputs']==[]


def test_late_output_patch_is_saved_with_final_output_and_source_target(root):
    approved=json.loads((root/'prototype/approved'/FILENAME).read_text())
    tools=ParameterTools(root,approved);plan=fixed_plan(approved)
    out=output_definition(tools,plan[0]['selected_api_id']);queue=[]
    for index,current in enumerate(plan[1:]):
        c=empty_proposal(current)
        field=next(x for x in candidate(tools,current,{})['inputs'] if x['field']=='ordNo')
        field.update(source='bind',origin='previous_output',ref='b-'+current['step_id'],value=None)
        c['inputs']=[field]
        c['bindings']=[dict(binding_id=field['ref'],to_parameter_path=field['parameter_path'],**{'from':dict(
            from_step_id='1-1',output_name='ordNo',**{k:out[k] for k in ['response_key','content_type','response_path','path_type','row_scope']})})]
        queue.append(api_response(read_calls(tools,current)))
        if index==0:
            queue.append(api_response([dict(type='function_call',id='source-read',call_id='source-read',name='get_response_outputs',
                arguments=json.dumps({'selected_api_id':plan[0]['selected_api_id']}),status='completed')]))
        queue.append(api_response(content=json.dumps(c)))
    def create(**kwargs):return queue.pop(0)
    class LegacyProducer(Runtime):
        def run(self,current,previous,*args):
            # Simulate a previously accepted producer with no defined outputs.
            if current['step_id']=='1-1':return empty_proposal(current)
            return super().run(current,previous,*args)
    result=generate(root,FILENAME,runtime_factory=lambda tools,config:LegacyProducer(
        tools,config,client=NS(responses=NS(create=create)),model='test'))
    ir=json.loads((root/result['file']).read_text())
    source=ir['tasks'][0]['steps'][0]
    assert source['outputs'][0]['response_path']==out['response_path']
    assert source['inputs']==[] and source['api']['api_id']==plan[0]['selected_api_id']
    assert ir['tasks'][0]['target']['source_step_id']=='1-1'
    assert ir['final_outputs'][0]['ref']['from_step_id']=='1-1'
    assert ir['tasks'][1]['depends_on']==[1]
    events=[json.loads(line) for line in (root/result['log_file']).read_text().splitlines()]
    assert sum(e['event']=='backend_output_defined' for e in events)==1


def test_review_draft_generates_before_approval(root):
    """최종 등록 화면 — 승인 전 검토용 초안(approval_status review)으로도 IR 을 만든다. 행 상태가 섞이거나 미승인이면 거부 (2026-11-12)."""
    data=json.loads((root/'prototype/approved'/FILENAME).read_text(encoding='utf-8-sig'))
    data['approval_status']='review'
    for row in data['api_selection_results']: row['approval_status']='review'
    (root/'prototype/approved/review-test.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    ir=generate(root,'review-test.json',runtime_factory=FakeRuntime)['ir']
    assert [s['step_id'] for t in ir['tasks'] for s in t['steps']]==['1-1','2-1','2-2','2-3']
    data['api_selection_results'][0]['approval_status']='approved'
    with pytest.raises(ValueError, match='미승인 API'): fixed_plan(data)
    data['approval_status']='unapproved'
    with pytest.raises(ValueError, match='검토 전 초안'): fixed_plan(data)
