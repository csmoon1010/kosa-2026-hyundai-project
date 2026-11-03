"""Dependency-based prompt views. Backend state and evidence offsets stay intact."""
from copy import deepcopy
import json


def project_context(current, previous, following):
    incoming = current.get('input_dependencies', [])
    outgoing = current.get('output_consumers', [])
    ids = set()
    names = {}
    for dependency in incoming:
        source = dependency.get('source_step_id')
        if source:
            ids.add(source)
            selected = dependency.get('source_output_names')
            if selected and (source not in names or names[source] is not None):
                names.setdefault(source, set()).update(selected)
            else:
                names[source] = None  # STEP-level reference: preserve all outputs.
        else:
            ids.update(dependency.get('candidate_source_step_ids', []))
    # Older inputs need not carry complete dependency metadata. Keep all output
    # definitions when the producer cannot be identified; still omit input history.
    fallback = bool(previous) and (not incoming or any(not d.get('source_step_id') and
                  not d.get('candidate_source_step_ids') for d in incoming))
    if fallback:
        ids.update(previous)
    view = {}
    for sid, step in previous.items():
        if sid not in ids:
            continue
        outputs = []
        selected = None if fallback else names.get(sid)
        if selected and not selected.issubset({o.get('name') for o in step.get('outputs', [])}):
            selected = None  # An unresolved output name is not proof of absence.
        for i, output in enumerate(step.get('outputs', [])):
            if selected and output.get('name') not in selected:
                continue
            outputs.append({**deepcopy(output),
                            'source_pointer': f'/previous_steps/{sid}/outputs/{i}'})
        view[sid] = dict(step_id=sid, api=deepcopy(step.get('api', {})), outputs=outputs)
    consumers = {d.get('consumer_task_sequence') for d in outgoing}
    # Explicit empty consumer metadata is not proof that no later task needs
    # this output. Preserve slim downstream conditions if the relation is unknown.
    future = []
    for step in following:
        if consumers and step.get('path_sequence') not in consumers:
            continue
        task = step.get('intent_task', {})
        slim_task = {k: deepcopy(task[k]) for k in ('sequence', 'action', 'conditions') if k in task}
        conditions = slim_task.get('conditions')
        if consumers and isinstance(conditions, list):
            slim_task['conditions'] = [c for c in conditions if not isinstance(c, dict) or
                not (c.get('source_step_id') or c.get('source_task_sequence')) or
                c.get('source_step_id') == current.get('step_id') or
                c.get('source_task_sequence') == current.get('path_sequence')]
        dependencies = step.get('input_dependencies', [])
        if consumers:
            dependencies = [d for d in dependencies if d.get('source_step_id') == current.get('step_id') or
                            current.get('step_id') in d.get('candidate_source_step_ids', [])]
        future.append(dict(step_id=step['step_id'], selected_api_id=step['selected_api_id'],
                           intent_task=slim_task, input_dependencies=deepcopy(dependencies)))
    return view, future, dict(fallback=fallback, previous_before=len(previous), previous_after=len(view),
                             following_before=len(following), following_after=len(future),
                             before_chars=len(json.dumps([previous, following], ensure_ascii=False)),
                             after_chars=len(json.dumps([view, future], ensure_ascii=False)))
