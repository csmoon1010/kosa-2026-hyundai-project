"""Final recheck of the selected inputs, outputs, and bindings only."""
from copy import deepcopy


class FinalValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('최종 매핑 검증 실패: ' + '; '.join(e['message'] for e in errors))


def validate_final_ir(ir, tools, plan):
    """Re-run the three mapping sections after deterministic IR assembly.

    Task metadata, unresolved issue bookkeeping, assertions, task ordering,
    dependency assembly, and final-output synthesis are outside this gate.
    The approved plan and IR builder own those structures.
    """
    expected = {step['step_id']: step for step in plan}
    by_step = {step['step_id']: step for task in ir.get('tasks', [])
               for step in task.get('steps', [])}
    previous, errors = {}, []
    for sid, current in expected.items():
        step = by_step.get(sid)
        if step is None:
            continue
        candidate = {key: deepcopy(step.get(key, []))
                     for key in ['inputs', 'outputs', 'bindings']}
        verdict = tools.validate(candidate, current, previous)
        errors.extend(dict(**error, owner='mapping', step_id=sid)
                      for error in verdict['errors'])
        previous[sid] = step
    if errors:
        raise FinalValidationError(errors)
    return dict(valid=True, errors=[], warnings=[])
