"""Resolve explicit result dependencies without adding or reordering approved STEPs.

업무 사이: 업무 조건의 "N번 업무에서 조회한 …" · 구조화 기록(source_task_sequence · source_step_id).
같은 업무 안(2026-11-05 지은 병합): 출처 단계가 소비 단계보다 앞이면 허용하고, 관계는 출처 단계 뒤의 단계에만 붙인다.
  - 업무 조건의 구조화 기록이 같은 업무의 단계(source_step_id)를 가리킬 때
  - 승인본 행(api_selection_results)에 source_step_id 가 있을 때 — 그 행 하나에만 붙인다
"""
import re
import json
from copy import deepcopy

EXPLICIT_RESULT = re.compile(r'(\d+)\s*번\s*(?:업무|작업)\s*(?:에서|의)?\s*(?:조회한|조회된|조회\s*결과|결과|출력)')
IMPLICIT_RESULT = re.compile(r'조회\s*(?:결과|한|된)|이전\s*(?:업무|단계).*(?:결과|출력)')


def _condition_records(value):
    if isinstance(value, list):
        return [row for child in value for row in _condition_records(child)]
    if isinstance(value, dict):
        return [value] + [row for child in value.values() if isinstance(child, (dict, list))
                          for row in _condition_records(child)]
    return []


def _order(step):
    return (step['path_sequence'], step['step'])


def attach_dependencies(plan, tasks):
    taskmap = {task['sequence']: task for task in tasks}
    for step in plan:
        step.update(intent_task=deepcopy(taskmap[step['path_sequence']]), input_dependencies=[], output_consumers=[])
    for index, task in enumerate(tasks):
        raw_conditions = task.get('conditions') or ''
        conditions = raw_conditions if isinstance(raw_conditions, str) else json.dumps(raw_conditions, ensure_ascii=False)
        records = _condition_records(raw_conditions)
        explicit_sequences = {r['source_task_sequence'] for r in records
                              if type(r.get('source_task_sequence')) is int}
        explicit_steps = {r['source_step_id'] for r in records if isinstance(r.get('source_step_id'), str)}
        explicit_sequences.update(s['path_sequence'] for s in plan if s['step_id'] in explicit_steps)
        references = sorted({int(x) for x in EXPLICIT_RESULT.findall(conditions)} | explicit_sequences)
        implicit_candidates = []
        if not references and IMPLICIT_RESULT.search(conditions):
            implicit_candidates = [s for s in plan if s['path_sequence'] < task['sequence']
                                   and '조회' in (s.get('edge', '') + taskmap[s['path_sequence']].get('action', ''))]
            references = sorted({s['path_sequence'] for s in implicit_candidates}) if len(implicit_candidates) == 1 else []
        sources = [(n, [s for s in plan if s['path_sequence'] == n]) for n in references]
        if not sources and implicit_candidates:
            sources = [(None, implicit_candidates)]
        for source_task, candidates in sources:
            queries = [s for s in candidates if '조회' in s.get('edge', '')]
            named = [s for s in candidates if s['step_id'] in explicit_steps]
            source = named[0] if len(named) == 1 else candidates[0] if len(candidates) == 1 else queries[0] if len(queries) == 1 else None
            same_task = source_task == task['sequence']
            if source_task is not None and source_task > task['sequence']:
                source = None
            if same_task and source is None:
                continue                        # 같은 업무인데 출처 단계를 못 정함 — 자기 업무를 '모호한 출처'로 남기지 않는다
            dependency = dict(dependency_id=f'D-{source_task or "unknown"}-to-{task["sequence"]}',
                source_task_sequence=source_task, consumer_task_sequence=task['sequence'],
                source_step_id=source['step_id'] if source else None,
                source_api_id=source['selected_api_id'] if source else None,
                candidate_source_step_ids=[s['step_id'] for s in candidates],
                conditions=conditions, source_pointer=f'/intent_tasks/{index}/conditions',
                status='resolved' if source else 'ambiguous')
            names = {name for record in records if source and
                     (record.get('source_step_id') == source['step_id'] or record.get('source_task_sequence') == source_task)
                     for name in (record.get('source_output_names') or []) if isinstance(name, str)}
            if names:
                dependency['source_output_names'] = sorted(names)
            if same_task:
                dependency['dependency_id'] = f'D-{source["step_id"]}-to-{task["sequence"]}'
            for step in plan:
                if step['path_sequence'] == task['sequence'] and (not same_task or _order(step) > _order(source)):
                    step['input_dependencies'].append(deepcopy(dependency))
                if source and step['step_id'] == source['step_id']:
                    step['output_consumers'].append(deepcopy(dependency))
    _attach_row_sources(plan)
    return plan


def _attach_row_sources(plan):
    """승인본 행의 source_step_id — 그 행(소비 단계)만 출처 단계의 결과를 쓴다. 출처는 소비 단계보다 앞이어야 한다."""
    by_id = {step['step_id']: step for step in plan}
    for index, step in enumerate(plan):
        source_id = step.get('source_step_id')
        if not isinstance(source_id, str):
            continue
        source = by_id.get(source_id)
        if source is None or _order(source) >= _order(step):
            raise ValueError(f'{step["step_id"]} 의 source_step_id {source_id} 는 앞 단계가 아닙니다')
        if any(d.get('source_step_id') == source_id for d in step['input_dependencies']):
            continue                            # 업무 조건으로 이미 같은 출처가 붙음
        dependency = dict(dependency_id=f'D-{source_id}-to-{step["step_id"]}',
            source_task_sequence=source['path_sequence'], consumer_task_sequence=step['path_sequence'],
            source_step_id=source_id, source_api_id=source['selected_api_id'], candidate_source_step_ids=[source_id],
            conditions=step['intent_task'].get('conditions'),
            source_pointer=f'/api_selection_results/{index}/source_step_id',   # 승인본 행이 (업무, 단계) 순일 때 정확 (handoff 가 그렇게 만든다)
            status='resolved')
        names = step.get('source_output_names')
        if isinstance(names, list) and all(isinstance(n, str) for n in names) and names:
            dependency['source_output_names'] = sorted(set(names))
        step['input_dependencies'].append(deepcopy(dependency))
        source['output_consumers'].append(deepcopy(dependency))
