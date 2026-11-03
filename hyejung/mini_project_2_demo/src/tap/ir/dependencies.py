"""Resolve explicit result dependencies without adding or reordering approved STEPs."""
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
            if source_task is not None and source_task >= task['sequence']:
                source = None
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
            for step in plan:
                if step['path_sequence'] == task['sequence']:
                    step['input_dependencies'].append(deepcopy(dependency))
                if source and step['step_id'] == source['step_id']:
                    step['output_consumers'].append(deepcopy(dependency))
    return plan
