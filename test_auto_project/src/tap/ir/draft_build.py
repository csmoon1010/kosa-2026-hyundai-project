"""Approved selection -> deterministic tasks -> agent mappings -> saved draft."""
import json
import uuid
import time
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from tap.agent.parameter_tools import ParameterTools
from tap.agent.config import configuration, generation_policy, generation_options as normalize_options
from tap.agent.runtime import Runtime
from tap.agent.budget import calculate, configuration_for
from tap.agent.mapping_validation import issue
from tap.ir.draft_validate import validate_final_ir, FinalValidationError
from tap.ir.dependencies import attach_dependencies
from tap.ir.xml_preview import build_xml_preview


def approved_path(root, filename):
    if not isinstance(filename,str) or Path(filename).name != filename or not filename.endswith('.json'):
        raise ValueError('승인 파일 이름을 선택하세요')
    folder=(Path(root)/'prototype/approved').resolve()
    p=(folder/filename).resolve()
    if p.parent!=folder or not p.is_file(): raise ValueError('승인 파일이 없습니다')
    return p


def fixed_plan(approved):
    if approved.get('approval_status')!='approved': raise ValueError('전체 승인본만 생성할 수 있습니다')
    tasks=approved.get('intent_tasks',[])
    seqs=[t['sequence'] for t in tasks]
    if not seqs or any(type(n) is not int or n<1 for n in seqs) or any(type(t.get('count')) is not int or t['count']<1 for t in tasks) or len(set(seqs))!=len(seqs): raise ValueError('업무 번호 오류')
    taskmap={t['sequence']:t for t in tasks}
    plan=[]
    for row in sorted(approved['api_selection_results'],key=lambda x:(x['path_sequence'],x['step'])):
        n,k=row['path_sequence'],row['step']
        if n not in taskmap or row['domain']!=taskmap[n]['domain'] or type(k) is not int or k<1: raise ValueError('업무·단계 대응 오류')
        if row.get('approval_status')!='approved' or not row.get('selected_api_id') or row['selected_api_id'] not in row['api_candidates']: raise ValueError('미승인 API')
        plan.append({**row,'step_id':f'{n}-{k}'})
    if len({x['step_id'] for x in plan})!=len(plan) or {x['path_sequence'] for x in plan}!=set(seqs): raise ValueError('단계 누락 또는 중복')
    return attach_dependencies(plan, tasks)


def _assemble(filename, approved, plan, config, tools, runtime, result_provider, on_event=None, log_file=None):
    tasks=[]; previous={}; issues=[]; step_previews={}
    if on_event:
        on_event(dict(event='scenario_steps',steps=[dict(step_id=s['step_id'],edge=s['edge'],
            task_sequence=s['path_sequence'],task_action=s['intent_task']['action'],conditions=s['intent_task'].get('conditions'),
            api={'api_id':s['selected_api_id']}) for s in plan]))
    for i,u in enumerate(approved.get('unresolved',[]),1):
        ids=[s['step_id'] for s in plan if s['path_sequence']==u['path_sequence'] and (u['step'] is None or s['step']==u['step'])]
        issues.append(dict(issue_id=f'U-INPUT-{i}',status='open',task_sequence=u['path_sequence'],step_ids=ids,parameter_paths=[],reason=u['reason'],required_input=u['reason'],resolution=None,evidence=[]))
    for task in sorted(approved['intent_tasks'],key=lambda x:x['sequence']):
        out={**task,'depends_on':sorted({d['source_task_sequence'] for s in plan if s['path_sequence']==task['sequence'] for d in s.get('input_dependencies',[]) if d['source_task_sequence'] is not None and d['source_task_sequence'] < task['sequence']}),'graph_id':None,'from_state':None,'to_state':None,'target':None,'steps':[]}
        for current in [s for s in plan if s['path_sequence']==task['sequence']]:
            started = time.monotonic()
            schema=tools.schema(current['selected_api_id'])
            if not schema: raise ValueError('요청 스키마 없음: '+current['selected_api_id'])
            if on_event:
                on_event(dict(event='backend_canonical',step_id=current['step_id'],turn=runtime.usage['llm_calls'],
                              usage=dict(runtime.usage),backend_seconds=round(time.monotonic()-started,3),
                              request={'selected_api_id':current['selected_api_id']},
                              result={'method':schema['method'],'endpoint':schema['endpoint'],'content_type':schema.get('contentType')}))
            result=result_provider(current,previous,task,approved['original_question'],[s for s in plan if (s['path_sequence'],s['step'])>(current['path_sequence'],current['step'])])
            started = time.monotonic()
            baseline = tools.read('get_baseline_request', current['selected_api_id'])
            baseline_data = baseline.get('data', {})
            baseline_values = {x.get('parameter_path', x.get('path')): x for x in baseline_data.get('parameters', [])}
            schema_fields = {x['path']: x for x in schema.get('parameters', [])}
            candidate_inputs = deepcopy(result['inputs'])
            for item in result['inputs']:
                path = item.get('parameter_path')
                definition = schema_fields.get(path, {})
                present = path in baseline_values
                original = baseline_values.get(path, {})
                for key, fallback in [('field', definition.get('name', path or '미지정')),
                                      ('type', definition.get('type')), ('xml_path', definition.get('xmlPath')),
                                      ('source','unresolved'), ('origin','unresolved'), ('reason','매핑 후보')]:
                    if item.get(key) is None: item[key] = fallback
                item.setdefault('value', None)
                item.setdefault('ref', None)
                item.setdefault('evidence', [])
                item['baseline_value'] = original.get('value')
                item['baseline_value_source'] = original.get('value_source')
                item['baseline_present'] = present
                item['comparison_reason'] = None if present else 'Baseline 문서가 없습니다' if baseline.get('missing') else 'Baseline에 해당 파라미터 경로가 없습니다'
                if item['source'] == 'bind':
                    item['change_kind'] = 'response_binding'
                elif item['source'] in ['unresolved','run_input']:
                    item['change_kind'] = 'input_needed'
                elif not present:
                    item['change_kind'] = 'comparison_unavailable'
                else:
                    value, original_value = item['value'], original.get('value')
                    same = type(value) is type(original_value) and value == original_value
                    item['change_kind'] = 'unchanged' if same else 'replace'
            if on_event:
                on_event(dict(event='backend_baseline_compare',step_id=current['step_id'],turn=runtime.usage['llm_calls'],
                              usage=dict(runtime.usage),backend_seconds=round(time.monotonic()-started,3),
                              request={'selected_api_id':current['selected_api_id'],'candidates':candidate_inputs},
                              result={'baseline_source_id':baseline.get('source_id'),'baseline_file':baseline.get('source_file'),
                                      'validation_status':baseline_data.get('validation_status'),'comparisons':result['inputs']}))

            step=dict(step_id=current['step_id'],step=current['step'],type='call',edge=current['edge'],from_state=None,to_state=None,api=dict(api_id=current['selected_api_id'],method=schema['method'],endpoint=schema['endpoint'],selector=None),inputs=result['inputs'],outputs=result['outputs'],bindings=result['bindings'],assertions=result['assertions'],expect=None,unresolved=[])
            step['baseline'] = dict(file=baseline.get('source_file'), source=baseline_data.get('source'), validation_status=baseline_data.get('validation_status'))
            step['input_dependencies'] = deepcopy(current.get('input_dependencies', []))
            step['output_consumers'] = deepcopy(current.get('output_consumers', []))
            for x in step['inputs']:
                if x['field'] in ['procGb','prgrGb'] and x['source']=='fixed':
                    step['api']['selector']={**(step['api']['selector'] or {}),x['field']:x['value']}
            for b in step['bindings']:
                seq=int(b['from']['from_step_id'].split('-')[0])
                if seq!=task['sequence'] and seq not in out['depends_on']: out['depends_on'].append(seq)
                if out['target'] is None and b['from'].get('row_scope'):
                    out['target']=dict(source_step_id=b['from']['from_step_id'],row_scope=b['from']['row_scope'],count=task['count'])
            if out['target'] is None and step['outputs']:
                row=next((x['row_scope'] for x in step['outputs'] if x.get('row_scope')),None)
                if row: out['target']=dict(source_step_id=step['step_id'],row_scope=row,count=task['count'])
            newissues=list(result['unresolved'])
            # Assertions/required-field completeness are outside temporary replacement analysis.
            for x in step['inputs']:
                if x['source'] in ['unresolved','run_input']:
                    newissues.append(dict(reason=x['reason'],parameter_paths=[x['parameter_path']],required_input=x['reason']))
            for u in newissues:
                issues.append(dict(issue_id=f'U-GEN-{len(issues)+1}',status='open',task_sequence=task['sequence'],step_ids=[step['step_id']],parameter_paths=u.get('parameter_paths',[]),reason=u['reason'],required_input=u.get('required_input') or u['reason'],resolution=None,evidence=u.get('evidence',[]),dependency_ids=u.get('dependency_ids',[])))
            step['unresolved']=[u['issue_id'] for u in issues if step['step_id'] in u['step_ids']]
            out['steps'].append(step)
            previous[step['step_id']]=step
            step_previews[step['step_id']] = build_xml_preview(baseline_data.get('baseline_xml'), step['inputs'], step['bindings'])
            if on_event:
                on_event(dict(event='step_preview',step_id=step['step_id'],step=step,
                    task_sequence=task['sequence'],task_action=task['action'],conditions=task.get('conditions'),
                    preview=step_previews[step['step_id']],usage=dict(runtime.usage)))
        tasks.append(out)
    # A later STEP may have supplied a confirmed upstream output definition.
    for task in tasks:
        if task['target'] is None:
            for step in task['steps']:
                scope=next((o['row_scope'] for o in step['outputs'] if o.get('row_scope')),None)
                if scope:
                    task['target']=dict(source_step_id=step['step_id'],row_scope=scope,count=task['count'])
                    break
    now=datetime.now(ZoneInfo('Asia/Seoul'))
    sid=f'SCN-{now:%Y%m%d}-{uuid.uuid4().hex[:12]}'
    final=[]
    for step in previous.values():
        for o in step['outputs']:
            if o['name'].lower().endswith(('no','code','id')):
                final.append(dict(name=o['name'],ref=dict(from_step_id=step['step_id'],output_name=o['name'],**{k:o[k] for k in ['response_key','content_type','response_path','path_type','row_scope']})))
    ir=dict(scenario_id=sid,version=1,created_at=now.isoformat(),ir_version='approved-selection-draft-v1',original_question=approved['original_question'],status='needs_input',sources=dict(approved=dict(source_id='approved',file='prototype/approved/'+filename,version=None),source_files=approved.get('source_files',{}),artifacts=tools.used_sources),tasks=tasks,final_outputs=final,unresolved=issues,generation=dict(config=config,usage=runtime.usage,trace=runtime.trace))
    ir['generation']['log_file'] = log_file
    ir['generation']['mode'] = 'baseline_replacements'
    ir['generation']['tool_policy'] = 'kb_first_conditional'
    return dict(ir=ir,usage=runtime.usage,step_previews=step_previews)


def _generate(root, filename, config=None, runtime_factory=Runtime, on_event=None, log_file=None, generation_mode=None, generation_options=None):
    root = Path(root)
    options = normalize_options(generation_options, generation_mode)
    mode, policy = generation_policy('validated' if options['stop_retry'] else 'basic')
    legacy = configuration(config) if config is not None else None
    approved = json.loads(approved_path(root, filename).read_text(encoding='utf-8-sig'))
    plan = fixed_plan(approved)
    budget = calculate(len(plan), legacy)
    config = legacy or configuration_for(budget)
    tools = ParameterTools(root, approved, defer_optional_errors=(mode == 'validated'))
    runtime = runtime_factory(tools, config)
    if hasattr(runtime, 'set_options'):
        runtime.set_options(options)
    elif options['kb_rag'] or options['dependency_projection'] or options['injection_guard']:
        raise ValueError('선택한 runtime_factory가 추가 생성 옵션을 지원하지 않습니다')
    elif mode != 'basic': runtime.set_mode(mode)
    runtime.on_event = on_event
    runtime.budget = budget
    if on_event: on_event(dict(event="budget_initialized", budget=budget, budget_usage=runtime.budget_usage() if hasattr(runtime,"budget_usage") else {}))
    results = {}
    task_by_sequence = {task['sequence']: task for task in approved.get('intent_tasks', [])}
    def sync_outputs(previous):
        for sid, step in previous.items():
            if sid in results: results[sid]['outputs'] = deepcopy(step['outputs'])
    def collect(current, previous, *args):
        runtime_current = current
        if options['kb_rag']:
            runtime_current = deepcopy(current)
            candidates = []
            for candidate in plan:
                if candidate['step_id'] == current['step_id']:
                    continue
                candidate_task = task_by_sequence[candidate['path_sequence']]
                candidates.append(dict(step_id=candidate['step_id'],
                    task_sequence=candidate['path_sequence'], edge=candidate.get('edge'),
                    action=candidate_task.get('action'), api_id=candidate.get('selected_api_id'),
                    conditions=deepcopy(candidate_task.get('conditions'))))
            runtime_current['related_step_candidates'] = candidates
        result = runtime.run(runtime_current, previous, *args)
        sync_outputs(previous)
        results[current['step_id']] = deepcopy(result)
        return result
    def assemble(provider, emit):
        return _assemble(filename, approved, plan, config, tools, runtime, provider, emit, log_file)
    result = assemble(collect, on_event)
    identity = {k:result['ir'][k] for k in ['scenario_id','created_at']}
    if policy['final_ir_validation']:
        while True:
            started = time.monotonic()
            try:
                verdict = validate_final_ir(result['ir'], tools, plan)
            except FinalValidationError as error:
                verdict = dict(valid=False, errors=error.errors, warnings=[])
                known_ids = {s['step_id'] for s in plan}
                sid = next((e['step_id'] for e in error.errors if e.get('step_id') in known_ids), plan[0]['step_id'])
                current = next(s for s in plan if s['step_id'] == sid)
                runtime.emit('final_ir_validation', current, runtime.sessions[sid]['step_turn'],
                             backend_seconds=time.monotonic()-started,
                             request={'scenario_id':result['ir']['scenario_id']}, result=verdict)
                if any(e['owner'] == 'backend' for e in error.errors):
                    runtime.stop(current, runtime.sessions[sid]['step_turn'], verdict, runtime.errors['final_backend'])
                position = [s['step_id'] for s in plan].index(sid)
                earlier = {s['step_id'] for s in plan[:position]}
                previous = {s['step_id']:s for t in result['ir']['tasks'] for s in t['steps'] if s['step_id'] in earlier}
                repaired = runtime.repair(current, previous, [e for e in error.errors if e['step_id'] == sid])
                sync_outputs(previous)
                results[sid] = deepcopy(repaired)
                result = assemble(lambda current, *_:deepcopy(results[current['step_id']]), on_event)
                result['ir'].update(identity)
            except Exception as error:
                verdict = dict(valid=False, errors=[dict(**issue('FINAL_IR_BACKEND_ERROR', '/', str(error),
                    action='STOP'), owner='backend', step_id=None)], warnings=[])
                runtime.emit('final_ir_validation', plan[-1], runtime.sessions[plan[-1]['step_id']]['step_turn'],
                             backend_seconds=time.monotonic()-started, request={'scenario_id':result['ir']['scenario_id']}, result=verdict)
                runtime.stop(plan[-1], runtime.sessions[plan[-1]['step_id']]['step_turn'], verdict, runtime.errors['final_check'])
            else:
                runtime.emit('final_ir_validation', plan[-1], runtime.sessions[plan[-1]['step_id']]['step_turn'],
                             backend_seconds=time.monotonic()-started,
                             request={'scenario_id':result['ir']['scenario_id']}, result=verdict)
                break
    elif on_event:
        on_event(dict(event='ir_validation_skipped', reason='기본 모드: 매핑·필수값 검증 미수행', usage=runtime.usage))
    ir = result['ir']
    if hasattr(runtime, '_remaining'): runtime._remaining()
    ir['generation']['budget'] = budget
    ir['generation']['budget_usage'] = runtime.budget_usage() if hasattr(runtime,'budget_usage') else {}
    result.update(budget=budget, budget_usage=ir['generation']['budget_usage'])
    ir['generation']['options'] = options
    ir['generation']['execution_mode'] = mode
    ir['generation']['policy'] = deepcopy(policy)
    ir['generation']['validation'] = dict(mapping=policy['mapping_validation'], required_fields=False,
                                         final_mapping=policy['final_ir_validation'])
    ir['sources']['artifacts'] = tools.used_sources
    dest = root/'data/out/scenario_ir_drafts'/f"{ir['scenario_id']}-v1.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    pending = dest.with_suffix('.json.tmp')
    try:
        pending.write_text(json.dumps(ir, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        pending.replace(dest)
    finally:
        pending.unlink(missing_ok=True)
    if hasattr(runtime, '_remaining'): runtime._remaining()
    result['file'] = str(dest.relative_to(root))
    if options['approval_gate']:
        from .input_review import initialize
        review = initialize(root, ir, result['file'], result['step_previews'], tools, on_event)
        result.update(review)
    return result


def generate(root, filename, config=None, runtime_factory=Runtime, on_event=None, generation_mode=None, generation_options=None):
    """Always journal input, model/tool events and terminal outcome, including failures."""
    from tap.agent.logging import GenerationJournal
    import traceback
    journal = GenerationJournal(Path(root))
    def emit(event):
        record = journal.append(event)  # persist before attempting UI delivery
        if on_event: on_event(record)
    try:
        options = normalize_options(generation_options, generation_mode)
        mode, policy = generation_policy('validated' if options['stop_retry'] else 'basic')
        emit(dict(event='generation_start', approved_filename=filename, config=config,
                  execution_mode=mode, options=options, policy=policy, log_file=journal.file, log_url=journal.url))
        result = _generate(root, filename, config, runtime_factory, emit, journal.file, mode, options)
        result.update(log_file=journal.file, log_url=journal.url)
        journal.append(dict(event='generation_complete', result=result, usage=result['usage']))
        return result
    except Exception as error:
        journal.append(dict(event='generation_error', error=str(error), traceback=traceback.format_exc(),
                            usage=journal.usage, log_file=journal.file, log_url=journal.url))
        error.log_file = journal.file
        error.log_url = journal.url
        raise
    finally:
        journal.close()
