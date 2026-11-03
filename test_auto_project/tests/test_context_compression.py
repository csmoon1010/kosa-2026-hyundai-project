"""All eight option combinations through real runtime, backend gates and save."""
import itertools
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from test_scenario_ir_drafts import root, FILENAME, api_response
from test_scenario_ir_modes import context, scenario_queue, fixed_candidate
from tap.agent.config import generation_options, harness_configuration, configuration
from tap.agent.context_projection import project_context
from tap.agent.kb_retrieval import KBRetriever, ExistingChromaIndex, MODEL, condition_queries, validate_top_k
from tap.agent.runtime import Runtime
from tap.agent.tool_registry import ToolRegistry
from tap.ir.draft_build import generate

COMBINATIONS = list(itertools.product([False, True], repeat=3))


class DeterministicRetriever:
    """Select actual field definitions, without external embedding/model calls."""
    def select(self, full, canonical, conditions, scope='search', paths=None, budget=None, **context):
        if budget: budget()
        self.last_context = context
        result = deepcopy(full)
        fields = result['data']['parameters']
        wanted = set(paths or [])
        if scope != 'full':
            result['data']['parameters'] = [f for f in fields if
                f['identity']['parameter_name'] in ('venCd', 'ordNo') or f['identity']['parameter_path'] in wanted]
        result['retrieval'] = dict(top_k=5, scope=scope, fallback_reason=None,
            embedding_tokens=3, embedding_calls=1, embedding_seconds=0.01,
            total_fields=len(fields), selected_fields=len(result['data']['parameters']))
        return result


@pytest.mark.parametrize('stop_retry,kb_rag,dependency_projection', COMBINATIONS)
def test_all_eight_combinations_end_to_end(root, stop_retry, kb_rag, dependency_projection):
    approved, tools, plan = context(root, True)
    queue, proposals = scenario_queue(tools, plan)
    requests, events = [], []
    options = dict(stop_retry=stop_retry, kb_rag=kb_rag, dependency_projection=dependency_projection)
    def factory(tools, config):
        def create(**kwargs):
            requests.append(deepcopy(kwargs))
            return queue.pop(0)
        runtime = Runtime(tools, config, client=NS(responses=NS(create=create)), model='test')
        runtime.retriever = DeterministicRetriever()
        return runtime
    result = generate(root, FILENAME, runtime_factory=factory, on_event=events.append,
                      generation_options=options)
    ir = result['ir']
    assert not queue and len(requests) == 9
    assert ir['generation']['options'] == generation_options(options)
    assert ir['generation']['execution_mode'] == ('validated' if stop_retry else 'basic')
    assert ir['generation']['validation']['mapping'] is stop_retry
    assert ir == json.loads((root / result['file']).read_text())
    assert any(e['event'] == 'mapping_validation' for e in events) is stop_retry
    assert any(e['event'] == 'final_ir_validation' for e in events) is stop_retry
    assert any(e['event'] == 'kb_retrieval' for e in events) is kb_rag
    assert any(e['event'] == 'context_projection' for e in events) is dependency_projection
    kb_results = [e['result'] for e in events if e['event'] == 'tool_result' and e['tool'] == 'get_parameter_knowledge']
    assert all(('retrieval' in r) is kb_rag for r in kb_results)
    if kb_rag:
        assert ir['generation']['usage']['embedding_tokens'] == 12
        assert all(len(r['data']['parameters']) < r['retrieval']['total_fields'] for r in kb_results)
    if dependency_projection:
        projected = next(e['result']['selected_context'] for e in events
                         if e['event']=='context_projection' and e['step_id']=='2-1')
        assert list(projected['previous_steps']) == ['1-1']
        assert [s['step_id'] for s in projected['following_steps']] == ['2-2','2-3']
        # First request of the final STEP contains only the original producer,
        # with no preceding input/baseline history.
        payload = next(json.loads(r['input'][0]['content']) for r in requests
                       if json.loads(r['input'][0]['content'])['current_step']['step_id'] == '2-3')
        assert set(payload['previous_steps']) == {'1-1'}
        assert 'inputs' not in payload['previous_steps']['1-1']
        assert payload['previous_steps']['1-1']['outputs'][0]['source_pointer'].startswith('/previous_steps/1-1/outputs/')
    steps = [s for task in ir['tasks'] for s in task['steps']]
    assert steps[0]['inputs'][0]['value'] == '001442'
    assert all(s['bindings'][0]['from']['from_step_id'] == '1-1' for s in steps[1:])
    assert next(e for e in events if e['event'] == 'generation_start')['options'] == generation_options(options)


def test_legacy_and_strict_options():
    assert generation_options() == dict(stop_retry=False, kb_rag=False, dependency_projection=False, approval_gate=False, injection_guard=False)
    assert generation_options(mode='validated')['stop_retry']
    assert generation_options({'stop_retry': True, 'kb_rag': True}, 'validated')['kb_rag']
    for value in ([], 'true', {'kb_rag': 1}, {'extra': True}):
        with pytest.raises(ValueError): generation_options(value)
    with pytest.raises(ValueError, match='충돌'):
        generation_options({'stop_retry': False}, 'validated')
    for k in (0, 11, True, '5'):
        with pytest.raises(ValueError): validate_top_k(k)
    assert all(validate_top_k(k) == k for k in range(1, 11))
    assert condition_queries([{'search_query': '상품 가격', 'value': 50000, 'unit': '원'},
                              {'term': '설치상품', 'value': True}]) == ['상품 가격', '설치상품']


def test_projection_preserves_original_offsets_and_ambiguity():
    previous = {'a': dict(api={'api_id':'api-a'}, inputs=[{'large':'history'}], outputs=[
        dict(name='unused', response_path='/unused'), dict(name='ordNo',response_path='/order')]),
        'b': dict(api={'api_id':'api-b'}, outputs=[])}
    before = deepcopy(previous)
    current = dict(input_dependencies=[dict(source_step_id='a',source_output_names=['ordNo'])], output_consumers=[])
    view, _, _ = project_context(current, previous, [])
    assert set(view) == {'a'} and len(view['a']['outputs']) == 1
    assert view['a']['outputs'][0]['source_pointer'] == '/previous_steps/a/outputs/1'
    assert previous == before
    current['input_dependencies'] = [dict(source_step_id=None,candidate_source_step_ids=['a','b'],status='ambiguous')]
    view, _, _ = project_context(current, previous, [])
    assert set(view) == {'a','b'} and len(view['a']['outputs']) == 2


def test_kb_missing_candidate_requests_detail_without_spending_repair(root):
    approved, tools, plan = context(root)
    current = plan[0]
    registry = ToolRegistry(tools,current,{},harness_configuration()['errors'],retriever=DeterministicRetriever())
    full = tools.read('get_parameter_knowledge',current['selected_api_id'])
    registry.results['get_parameter_knowledge',current['selected_api_id']] = full
    registry.delivered_paths = set()
    value, feedback = registry.finish(json.dumps(fixed_candidate(tools,current)))
    assert value is None
    material = feedback['needed_materials'][0]
    assert material['scope'] == 'paths'
    result = registry.call_tool('get_parameter_knowledge',json.dumps({k:v for k,v in material.items() if k!='tool'}))
    assert 'error' not in result
    assert registry.finish(json.dumps(fixed_candidate(tools,current)))[0] is not None


def test_kb_fallback_preserves_all_original_pointers(root):
    _,tools,plan=context(root)
    api=plan[0]['selected_api_id'];full=tools.read('get_parameter_knowledge',api)
    index=NS(directory=root/'absent',_open=lambda: (_ for _ in ()).throw(FileNotFoundError('absent')))
    result=KBRetriever(root,index=index).select(full,tools.schema(api),'협력사 코드')
    assert result['data']==full['data'] and result['retrieval']['fallback_reason']=='absent'
    result=KBRetriever(root,index=index).select(full,tools.schema(api),[])
    assert result['retrieval']['fallback_reason']=='empty_conditions'


@pytest.mark.parametrize('options', [dict(stop_retry=True,kb_rag=a,dependency_projection=b)
                                    for a,b in itertools.product([False,True],repeat=2)])
def test_final_repair_keeps_options_and_projection(root, monkeypatch, options):
    import tap.ir.draft_build as build
    from tap.ir.draft_validate import FinalValidationError
    from tap.agent.mapping_validation import issue
    _,tools,plan=context(root,True);queue,proposals=scenario_queue(tools,plan)
    queue.append(api_response(content=json.dumps(proposals['2-3'])))
    requests=[]
    def factory(tools,config):
        def create(**kwargs):requests.append(deepcopy(kwargs));return queue.pop(0)
        runtime=Runtime(tools,config,client=NS(responses=NS(create=create)),model='test')
        runtime.retriever=DeterministicRetriever();return runtime
    original=build.validate_final_ir;calls=[]
    def once(ir,tools,plan):
        calls.append(1)
        if len(calls)==1:
            raise FinalValidationError([dict(**issue('EVIDENCE_MISMATCH','/inputs/0','test'),owner='mapping',step_id='2-3')])
        return original(ir,tools,plan)
    monkeypatch.setattr(build,'validate_final_ir',once)
    result=generate(root,FILENAME,runtime_factory=factory,generation_options=options)
    assert result['ir']['generation']['options']==generation_options(options) and not queue
    refreshed=next(json.loads(m['content'])['previous_steps'] for m in reversed(requests[-1]['input'])
                   if m.get('role')=='user' and 'previous_steps' in json.loads(m['content']))
    assert ('inputs' not in refreshed['1-1']) is options['dependency_projection']


def test_existing_chroma_query_without_paid_embedding():
    """Query an existing stored vector; proves local DB and API filtering work."""
    root=Path(__file__).resolve().parents[1]
    index=ExistingChromaIndex(root/'data/out/parameters/parameter_vectors',model_name=MODEL)
    collection=index._open()
    item=collection.get(limit=1,include=['metadatas','embeddings'])
    meta=item['metadatas'][0]
    result=collection.query(query_embeddings=[list(item['embeddings'][0])],n_results=5,
        where={'$and':[{'document_id':meta['document_id']},{'api_id':meta['api_id']},{'active':True}]},
        include=['metadatas','distances'])
    assert item['ids'][0] in result['ids'][0]
    assert all(m['api_id']==meta['api_id'] for m in result['metadatas'][0])


@pytest.mark.parametrize('bits', COMBINATIONS)
def test_transport_policy_is_independent_of_compression(root, bits):
    options=dict(zip(['stop_retry','kb_rag','dependency_projection'],bits))
    approved,tools,plan=context(root)
    current=plan[0];calls=[]
    def create(**kwargs):
        calls.append(1)
        raise TimeoutError('temporary')
    runtime=Runtime(tools,configuration(),client=NS(responses=NS(create=create)),model='test',generation_options=options)
    runtime.retriever=DeterministicRetriever()
    runtime.config['retry_base_seconds']=0
    with pytest.raises((ValueError,TimeoutError)):
        runtime.run(current,{},approved['intent_tasks'][0],approved['original_question'],[])
    assert len(calls)==(2 if options['stop_retry'] else 1)


@pytest.mark.parametrize('stream', [False, True])
def test_http_paths_forward_all_eight_options(root, monkeypatch, stream):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.request import Request,urlopen
    from tap.ui.serve import make_handler
    import tap.ir.draft_build as build
    seen=[]
    def fake(root,filename,config,on_event=None,**kwargs):
        options=generation_options(kwargs.get('generation_options'),kwargs.get('generation_mode'))
        seen.append(options)
        if on_event:on_event(dict(event='generation_start',options=options))
        return dict(ir={'generation':{'options':options}})
    monkeypatch.setattr(build,'generate',fake)
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(root))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        for bits in COMBINATIONS:
            options=dict(zip(['stop_retry','kb_rag','dependency_projection'],bits))
            body=json.dumps(dict(approved_filename=FILENAME,generation_options=options)).encode()
            request=Request(f'http://127.0.0.1:{server.server_port}/api/scenario-ir-drafts',data=body,
                headers={'Content-Type':'application/json','Accept':'application/x-ndjson' if stream else 'application/json'})
            with urlopen(request) as response:text=response.read().decode()
            result=json.loads(text.splitlines()[-1])['result'] if stream else json.loads(text)
            assert result['ir']['generation']['options']==generation_options(options)
        assert len(seen)==8
    finally:
        server.shutdown();server.server_close();thread.join()


def test_structured_conditions_keep_explicit_dependency_fields(root):
    from tap.ir.draft_build import fixed_plan
    approved,_,_=context(root)
    approved['intent_tasks'][1]['conditions']=[dict(search_query='주문 식별자',source_step_id='1-1',source_output_names=['ordNo'])]
    plan=fixed_plan(approved)
    dependency=plan[1]['input_dependencies'][0]
    assert dependency['source_step_id']=='1-1' and dependency['source_output_names']==['ordNo']
    assert plan[0]['output_consumers'][0]['consumer_task_sequence']==2


def test_approved_selection_reason_is_used_as_third_rag_query(root):
    _, tools, plan = context(root, True)
    current = plan[1]
    retriever = DeterministicRetriever()
    registry = ToolRegistry(tools,current,{},harness_configuration()['errors'],retriever=retriever)
    spec = next(item for item in registry.specs if item['name']=='get_parameter_knowledge')
    assert 'selection_reason' not in spec['parameters']['properties']
    query = current.get('selection_reason')
    result = registry.call_tool('get_parameter_knowledge',json.dumps({
        'selected_api_id':current['selected_api_id'],'scope':'search','parameter_paths':[]}))
    assert retriever.last_context['selection_reason'] == query
    assert retriever.last_context['original_question'] == tools.documents['approved']['original_question']
    assert 'dependency_link_context' not in result


def test_binding_type_compatibility_checked_even_without_validation_mode(root):
    _, tools, plan = context(root, True)
    current = plan[1]
    source_id = current['input_dependencies'][0]['source_step_id']
    previous = {source_id: dict(api={'api_id':plan[0]['selected_api_id']}, outputs=[
        dict(name='ordNo', type='object')])}
    registry = ToolRegistry(tools,current,previous,harness_configuration()['errors'])
    path = tools.schema(current['selected_api_id'])['parameters'][0]['path']
    feedback = registry._binding_compatibility_feedback({'bindings':[{
        'binding_id':'b1','from':{'from_step_id':source_id,'output_name':'ordNo'},
        'to_parameter_path':path}]})
    assert feedback and feedback['dependency_link_errors'][0]['reason'] == '출력·입력 타입 불일치'


def test_projection_only_does_not_advertise_kb_scope():
    config=harness_configuration(options={'dependency_projection':True})
    assert 'scope=expand' not in config['instructions']
    assert 'STEP 문맥 선별' in config['instructions']


def test_original_pointer_from_filtered_output_validates(root):
    _,tools,plan=context(root)
    previous={'1-1':dict(api={'api_id':plan[0]['selected_api_id']},outputs=[
        dict(name='unused',response_path='/unused'),dict(name='ordNo',response_path='/order')])}
    view,_,_=project_context(dict(input_dependencies=[dict(source_step_id='1-1',source_output_names=['ordNo'])]),previous,[])
    pointer=view['1-1']['outputs'][0]['source_pointer']+'/response_path'
    assert pointer=='/previous_steps/1-1/outputs/1/response_path'
    assert tools.evidence_valid(dict(source_id='approved',source_pointer=pointer,quote='/order'),previous=previous)


def test_embedding_usage_can_exhaust_shared_budget(root):
    approved,tools,plan=context(root)
    queue=[api_response([dict(type='function_call',id='kb',call_id='kb',name='get_parameter_knowledge',
                            arguments=json.dumps({'selected_api_id':plan[0]['selected_api_id']}))], tokens=(49990,8))]
    runtime=Runtime(tools,configuration({'max_tokens':50000,'max_output_tokens':4096}),
        client=NS(responses=NS(create=lambda **kwargs:queue.pop(0))),model='test',generation_options={'kb_rag':True})
    runtime.retriever=DeterministicRetriever()
    with pytest.raises(ValueError,match='RUN_TOKEN_LIMIT'):
        runtime.run(plan[0],{},approved['intent_tasks'][0],approved['original_question'],[])
    assert runtime.usage['embedding_tokens']==3 and runtime.usage['total_tokens']==50001


def fake_search_index(root,canonical):
    from tap.retrieval.chroma_index import build_parameter_search_text,digest
    metas=[];documents=[];queries=[]
    for f in canonical['parameters']:
        text=build_parameter_search_text(canonical,f,[])
        documents.append(text)
        metas.append(dict(document_id=canonical['documentId'],api_id=canonical['apiId'],
                          active=True,parameter_path=f['path'],content_hash=digest([text,f])))
    class Collection:
        def get(self,**kwargs):
            assert kwargs['where']['$and'][1]['api_id']==canonical['apiId']
            return dict(metadatas=metas,documents=documents)
        def query(self,**kwargs):
            queries.append(kwargs)
            count=kwargs['n_results'];size=len(kwargs['query_embeddings'])
            return dict(metadatas=[metas[:count] for _ in range(size)],distances=[[0.3]*count for _ in range(size)])
    embeddings=NS(create=lambda **kwargs:NS(data=[NS(index=i,embedding=[0.0]*1536) for i,_ in enumerate(kwargs['input'])],usage=NS(total_tokens=4)))
    return NS(directory=root/'data/out/parameters/parameter_vectors',_open=lambda:Collection(),
              _embedding_client=NS(embeddings=embeddings)),queries,metas


def test_per_condition_top_k_expansion_and_exact_path_lookup(root):
    _,tools,plan=context(root);api=plan[0]['selected_api_id'];canonical=tools.schema(api)
    full=tools.read('get_parameter_knowledge',api)
    index,queries,_=fake_search_index(root,canonical)
    retriever=KBRetriever(root,index=index)
    result=retriever.select(full,canonical,[{'search_query':'조건 A'},{'search_query':'조건 B'}])
    assert queries[0]['n_results']==5 and len(queries[0]['query_embeddings'])==2
    assert len(result['data']['parameters'])==5  # duplicates across conditions merged
    assert result['retrieval']['embedding_tokens']==4
    assert all(f['source_pointer'] in {f['source_pointer'] for f in full['data']['parameters']} for f in result['data']['parameters'])
    retriever.select(full,canonical,'조건 A',scope='expand')
    assert queries[-1]['n_results']==10
    path=full['data']['parameters'][-1]['identity']['parameter_path']
    result=retriever.select(full,canonical,'조건 A',scope='paths',paths=[path])
    assert len(queries)==2 and result['data']['parameters'][0]['identity']['parameter_path']==path
    with pytest.raises(ValueError):retriever.select(full,canonical,'조건',scope='paths',paths=['$.notHere'])


def test_stale_index_falls_back_without_embedding(root):
    _,tools,plan=context(root);api=plan[0]['selected_api_id'];canonical=tools.schema(api)
    full=tools.read('get_parameter_knowledge',api)
    index,queries,metas=fake_search_index(root,canonical)
    metas[0]['content_hash']='stale'
    result=KBRetriever(root,index=index).select(full,canonical,'조건')
    assert result['retrieval']['fallback_reason'].startswith('stale_index')
    assert result['retrieval']['embedding_tokens']==0 and not queries
    assert result['data']==full['data']


def test_projection_keeps_only_current_producer_consumer_conditions():
    current=dict(step_id='a',path_sequence=1,input_dependencies=[],output_consumers=[dict(consumer_task_sequence=3)])
    following=[dict(step_id='c',selected_api_id='api-c',path_sequence=3,intent_task=dict(sequence=3,conditions=[
        dict(search_query='a 사용',source_step_id='a'),dict(search_query='b 사용',source_step_id='b')]),
        input_dependencies=[dict(source_step_id='a'),dict(source_step_id='b')]),
        dict(step_id='d',selected_api_id='api-d',path_sequence=4,intent_task=dict(conditions='무관'))]
    _,future,_=project_context(current,{},following)
    assert len(future)==1
    assert future[0]['intent_task']['conditions']==[dict(search_query='a 사용',source_step_id='a')]
    assert future[0]['input_dependencies']==[dict(source_step_id='a')]


def test_failed_embedding_attempt_is_counted_before_full_fallback(root):
    _,tools,plan=context(root);api=plan[0]['selected_api_id'];canonical=tools.schema(api)
    full=tools.read('get_parameter_knowledge',api)
    index,queries,_=fake_search_index(root,canonical)
    def unavailable(**kwargs):raise TimeoutError('embedding unavailable')
    index._embedding_client.embeddings.create=unavailable
    result=KBRetriever(root,index=index).select(full,canonical,'조건')
    assert result['retrieval']['embedding_calls']==1
    assert result['retrieval']['embedding_tokens']==0
    assert result['retrieval']['fallback_reason']=='embedding unavailable'
    assert result['data']==full['data'] and not queries



def test_three_independent_retrieval_sources_are_top5_and_deduplicated(root):
    _,tools,plan=context(root);api=plan[0]['selected_api_id'];canonical=tools.schema(api)
    full=tools.read('get_parameter_knowledge',api)
    index,queries,_=fake_search_index(root,canonical)
    result=KBRetriever(root,index=index).select(full,canonical,'협력사 코드 001442',
        original_question='001442 협력사 주문을 조회',selection_reason='협력사 코드로 조회')
    assert queries[0]['n_results']==5 and len(queries[0]['query_embeddings'])==3
    rankings=result['retrieval']['rankings']
    assert [row['sources'] for row in rankings]==[['condition'],['original_question'],['selection_reason']]
    assert len(result['data']['parameters'])==5
    assert result['retrieval']['selected_fields']==len({f['identity']['parameter_path'] for f in result['data']['parameters']})


def test_retrieval_sources_deduplicate_identical_text_but_keep_origins(root):
    _,tools,plan=context(root);api=plan[0]['selected_api_id'];canonical=tools.schema(api)
    full=tools.read('get_parameter_knowledge',api);index,queries,_=fake_search_index(root,canonical)
    result=KBRetriever(root,index=index).select(full,canonical,'협력사 코드',
        original_question='협력사 코드',selection_reason='협력사 코드')
    assert len(queries[0]['query_embeddings'])==1
    assert result['retrieval']['rankings'][0]['sources']==['condition','original_question','selection_reason']
