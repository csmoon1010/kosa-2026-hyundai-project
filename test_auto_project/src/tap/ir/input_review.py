"""Persisted user decisions. No model calls and no business API execution."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid
from zoneinfo import ZoneInfo

from tap.agent.parameter_tools import ParameterTools
from tap.agent.mapping_validation import json_type
from .xml_preview import build_xml_preview


class ReviewConflict(ValueError):
    pass


def _now():
    return datetime.now(ZoneInfo('Asia/Seoul')).isoformat()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _path(root, scenario_id):
    if not isinstance(scenario_id, str) or not re.fullmatch(r'SCN-\d{8}-[a-f0-9]{12}', scenario_id):
        raise ValueError('올바른 scenario_id가 필요합니다')
    return Path(root) / 'data/out/scenario_ir_reviews' / (scenario_id + '.json')


def _file_hash(root, relative):
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('프로젝트 밖의 자료를 읽을 수 없습니다')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def _locked(path):
    """Process-wide file lock, including threaded and separate server instances."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.seek(0)
            if not stream.read(1):
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _event(state, name, **fields):
    event = dict(event=name, event_id=uuid.uuid4().hex, recorded_at=_now(),
                 scenario_id=state['ir']['scenario_id'], revision=state['revision'], **fields)
    state['audit'].append(event)
    return event


def _journal(root, state, event):
    # Review waiting time does not change generation usage or duration.
    relative = state['ir'].get('generation', {}).get('log_file')
    if not relative:
        return
    path = (Path(root) / relative).resolve()
    folder = (Path(root) / 'data/out/scenario_ir_logs').resolve()
    if path.parent == folder and re.fullmatch(r'IRRUN-[A-Za-z0-9-]+\.jsonl', path.name):
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({**event, 'run_id':path.stem}, ensure_ascii=False) + '\n')
            stream.flush()


def _summary(state):
    counts = dict(open_count=0, resolved_count=0, deferred_count=0)
    for target in state['targets']:
        choice = state['decisions'].get(target['target_id'], {}).get('choice', 'hold')
        counts[{'now':'resolved_count', 'runtime':'deferred_count', 'hold':'open_count'}[choice]] += 1
    return dict(status='confirmed' if state.get('confirmed') else
                'awaiting_decision' if counts['open_count'] else 'ready_for_confirmation',
                revision=state['revision'], **counts)


def _response(state):
    return dict(ir=state['ir'], review=state['ir']['review'], targets=state['targets'],
                decisions=state['decisions'], file=state['file'], step_previews=state['step_previews'])


def initialize(root, ir, draft_file, previews, tools, on_event=None):
    """Called only after a complete original draft was atomically saved."""
    if not ir['generation']['options'].get('approval_gate'):
        return None
    targets = {}
    steps = {s['step_id']:s for t in ir['tasks'] for s in t['steps']}
    for issue in ir['unresolved']:
        pairs = [(sid, path) for sid in issue.get('step_ids', [])
                 for path in issue.get('parameter_paths', [])]
        if not pairs:
            pairs = [(None, None)]
        for sid, path in pairs:
            step = steps.get(sid, {})
            api = step.get('api', {}).get('api_id')
            key = _digest([sid, api, path])[:24] if sid and path else 'issue-' + issue['issue_id']
            fields = {f['path']:f for f in tools.schema(api).get('parameters', [])} if api else {}
            field = fields.get(path, {})
            item = next((x for x in step.get('inputs', []) if x.get('parameter_path') == path), {})
            editable = bool(field and item.get('source') in ('unresolved', 'run_input')
                            and field.get('type') in ('string', 'integer', 'number', 'boolean')
                            and not issue.get('dependency_ids') and not re.search(r'\[|/rows/row(?:/|$)', path or '')
                            and not re.search(r'모호|의미|출처|관계|연결|불명', issue.get('reason') or ''))
            row = targets.setdefault(key, dict(target_id=key, step_id=sid, api_id=api,
                parameter_path=path, label=field.get('name') or path or '원본 검토 필요',
                type=field.get('type'), enum=deepcopy(field.get('enum')), issue_ids=[], reasons=[],
                editable=editable, baseline_value=item.get('baseline_value'),
                baseline_value_source=item.get('baseline_value_source')))
            row['editable'] = row['editable'] and editable
            if issue['issue_id'] not in row['issue_ids']:
                row['issue_ids'].append(issue['issue_id'])
            if issue.get('reason') not in row['reasons']:
                row['reasons'].append(issue.get('reason'))
    hashes = {}
    for relative in [ir['sources']['approved']['file']] + [s['file'] for s in ir['sources']['artifacts']]:
        hashes[relative] = _file_hash(root, relative)
    state = dict(ir=deepcopy(ir), base_ir=deepcopy(ir), revision=1, targets=list(targets.values()),
                 decisions={}, hashes=hashes, audit=[], confirmed=False, file=draft_file,
                 step_previews=deepcopy(previews))
    state['ir']['review'] = _summary(state)
    _atomic(Path(root)/draft_file, state['ir'])
    state['hashes'][draft_file] = _file_hash(root, draft_file)
    path = _path(root, ir['scenario_id'])
    event = _event(state, 'approval_gate_opened')
    with _locked(path):
        if path.exists():
            raise ReviewConflict('이미 검토 상태가 존재합니다')
        _atomic(path, state)
        if on_event:
            on_event(event)
        else:
            _journal(root, state, event)
    return _response(state)


def load(root, scenario_id):
    path = _path(root, scenario_id)
    if not path.is_file():
        raise ValueError('승인게이트가 적용된 검토 초안이 없습니다')
    return _response(json.loads(path.read_text(encoding='utf-8')))


def list_reviews(root):
    rows = []
    for path in sorted((Path(root)/'data/out/scenario_ir_reviews').glob('SCN-*.json'), reverse=True):
        state = json.loads(path.read_text(encoding='utf-8'))
        rows.append(dict(scenario_id=state['ir']['scenario_id'], review=state['ir']['review'],
                         original_question=state['ir']['original_question']))
    return rows


def _materials(root, state):
    for relative, expected in state['hashes'].items():
        try:
            matches = _file_hash(root, relative) == expected
        except OSError:
            matches = False
        if not matches:
            raise ReviewConflict('초안·승인본·자료가 변경되었습니다. 다시 생성하세요')
    approved = json.loads((Path(root)/state['base_ir']['sources']['approved']['file']).read_text(encoding='utf-8-sig'))
    return approved, ParameterTools(root, approved, defer_optional_errors=True)


def _rebuild(root, state, tools, approved):
    from .draft_build import fixed_plan
    ir = deepcopy(state['base_ir'])
    ir['version'] = state['revision']
    plan = {s['step_id']:s for s in fixed_plan(approved)}
    targets = {t['target_id']:t for t in state['targets']}
    document = {'decisions':state['decisions']}
    tools.documents['user-decisions'] = document
    ir['sources']['user_decisions'] = deepcopy(document)
    ir['runtime_inputs'] = []
    issue_targets = {}
    changed = set()
    for key, target in targets.items():
        for issue_id in target['issue_ids']:
            issue_targets.setdefault(issue_id, []).append(key)
    previous = {}
    previews = {}
    for task in ir['tasks']:
        for step in task['steps']:
            sid = step['step_id']
            for key, decision in state['decisions'].items():
                target = targets[key]
                if target['step_id'] != sid or decision['choice'] == 'hold':
                    continue
                item = next(x for x in step['inputs'] if x['parameter_path'] == target['parameter_path'])
                if decision['choice'] == 'now':
                    item.update(source='fixed', origin='user_condition', value=decision['value'], ref=None,
                        reason='사용자가 검토 화면에서 입력한 값', evidence=[dict(source_id='user-decisions',
                        source_pointer='/decisions/'+key+'/value', quote=str(decision['value']) if isinstance(decision['value'], str)
                        else json.dumps(decision['value'], ensure_ascii=False))])
                    item['change_kind'] = ('comparison_unavailable' if not item.get('baseline_present') else
                        'unchanged' if type(item['value']) is type(item.get('baseline_value')) and item['value']==item['baseline_value'] else 'replace')
                    changed.add(sid)
                else:
                    item.update(source='run_input', origin='run_input', value=None, ref=None,
                                reason='사용자가 실행 시 입력하도록 결정', change_kind='input_needed')
                    ir['runtime_inputs'].append(dict(input_key='INPUT-'+key, label=target['label'],
                        type=target['type'], enum=target['enum'], required=True,
                        step_id=sid, api_id=target['api_id'], parameter_path=target['parameter_path']))
                # Gate edits are always checked, even if generation mapping validation was OFF.
                verdict = tools.validate(dict(inputs=[item], outputs=[], bindings=[]), plan[sid], previous)
                if not verdict['valid']:
                    raise ValueError('입력 결정 검증 실패: '+json.dumps(verdict['errors'], ensure_ascii=False))
            step['api']['selector'] = None
            for item in step['inputs']:
                if item.get('field') in ('procGb', 'prgrGb') and item['source']=='fixed':
                    step['api']['selector'] = {**(step['api']['selector'] or {}), item['field']:item['value']}
            if ir['generation']['policy']['mapping_validation']:
                verdict = tools.validate(step, plan[sid], previous)
                if not verdict['valid']:
                    raise ValueError('결정본 매핑 검증 실패: '+json.dumps(verdict['errors'], ensure_ascii=False))
            baseline = tools.read('get_baseline_request', step['api']['api_id']).get('data', {})
            previews[sid] = build_xml_preview(baseline.get('baseline_xml'), step['inputs'], step['bindings'])
            previous[sid] = step
    # Values copied/interpreted by later tasks cannot be safely propagated without analysis.
    later_review = set()
    for sid in changed:
        source_task = next(t for t in ir['tasks'] if any(s['step_id']==sid for s in t['steps']))
        for task in ir['tasks']:
            if task['sequence'] < source_task['sequence']:
                continue
            for step in task['steps']:
                depends = source_task['sequence'] in task.get('depends_on', []) or any(
                    d.get('source_step_id')==sid for d in step.get('input_dependencies', []))
                source_pointer = '/previous_steps/' + sid
                referenced = any(i['source']=='fixed' and (
                    i.get('origin')=='previous_output' or any(
                        e.get('source_id')=='approved' and (
                            e.get('source_pointer')==source_pointer or
                            (e.get('source_pointer') or '').startswith(source_pointer+'/inputs/'))
                        for e in i.get('evidence', []))) for i in step['inputs'])
                if depends and step['step_id'] != sid and referenced:
                    later_review.add(step['step_id'])
    for issue in ir['unresolved']:
        keys = issue_targets.get(issue['issue_id'], [])
        choices = [state['decisions'].get(key, {}).get('choice', 'hold') for key in keys]
        issue['status'] = 'open' if not choices or 'hold' in choices else 'deferred' if 'runtime' in choices else 'resolved'
        issue['resolution'] = None if issue['status']=='open' else dict(target_ids=keys, revision=state['revision'])
    for sid in sorted(later_review):
        ir['unresolved'].append(dict(issue_id='RECHECK-'+sid, status='open', step_ids=[sid],
            parameter_paths=[], reason='선행 입력값 변경: 후속 고정값의 재검토가 필요합니다',
            required_input='원본 조건 검토 후 재생성', resolution=None, evidence=[]))
    for task in ir['tasks']:
        for step in task['steps']:
            step['unresolved'] = [u['issue_id'] for u in ir['unresolved'] if u['status']=='open' and step['step_id'] in u['step_ids']]
    state['ir'], state['step_previews'] = ir, previews
    ir['review'] = _summary(state)
    if later_review:
        ir['review']['open_count'] += len(later_review)
        ir['review']['status'] = 'awaiting_decision'
    return ir


def submit(root, scenario_id, body, confirm=False):
    if not isinstance(body, dict):
        raise ValueError('검토 요청은 JSON 객체여야 합니다')
    allowed = {'expected_revision'} if confirm else {'expected_revision', 'decisions'}
    if set(body)-allowed or type(body.get('expected_revision')) is not int:
        raise ValueError('expected_revision과 허용된 결정 항목만 전달하세요')
    path = _path(root, scenario_id)
    with _locked(path):
        if not path.is_file():
            raise ValueError('승인게이트가 적용된 검토 초안이 없습니다')
        state = json.loads(path.read_text(encoding='utf-8'))
        fingerprint = _digest([confirm, body])
        if state.get('last_request') == fingerprint:
            return _response(state)
        try:
            if not state['base_ir']['generation']['options'].get('approval_gate'):
                raise ValueError('이 실행에는 승인게이트가 적용되지 않았습니다')
            if body['expected_revision'] != state['revision']:
                raise ReviewConflict('다른 변경이 저장되었습니다. 검토 내용을 다시 불러오세요')
            if state['confirmed']:
                raise ReviewConflict('이미 확정된 결정본입니다. 새 초안을 생성하세요')
            approved, tools = _materials(root, state)
            if confirm:
                if state['ir']['review']['open_count']:
                    raise ValueError('보류·미해결 항목이 있어 확정할 수 없습니다')
            else:
                decisions = body.get('decisions')
                if not isinstance(decisions, list):
                    raise ValueError('decisions는 배열이어야 합니다')
                targets = {t['target_id']:t for t in state['targets']}
                seen = set()
                for decision in decisions:
                    if not isinstance(decision, dict) or set(decision)-{'target_id','choice','value'}:
                        raise ValueError('허용되지 않은 입력 결정입니다')
                    key, choice = decision.get('target_id'), decision.get('choice')
                    if not isinstance(key,str) or key not in targets or key in seen or choice not in ('now','runtime','hold'):
                        raise ValueError('입력 대상·선택값 또는 중복 결정을 확인하세요')
                    seen.add(key)
                    target = targets[key]
                    if choice != 'hold' and not target['editable']:
                        raise ValueError('값만 입력해 해결할 수 없는 항목입니다. 원본 조건을 검토하세요')
                    if choice == 'now':
                        value = decision.get('value')
                        actual = json_type(value)
                        if actual != target['type'] and not (target['type']=='number' and actual=='integer'):
                            raise ValueError('입력값 타입이 일치하지 않습니다')
                        if target['enum'] and value not in target['enum']:
                            raise ValueError('허용된 enum 값이 아닙니다')
                        if value == '' or (isinstance(value,float) and not math.isfinite(value)):
                            raise ValueError('빈 값 또는 유한하지 않은 숫자는 입력할 수 없습니다')
                    elif 'value' in decision:
                        raise ValueError('지금 입력 선택에만 value를 전달하세요')
                    state['decisions'][key] = deepcopy(decision)
            state['revision'] += 1
            _rebuild(root, state, tools, approved)
            if confirm:
                if state['ir']['review']['open_count']:
                    raise ValueError('재검토 항목이 있어 확정할 수 없습니다')
                state['confirmed'] = True
                state['ir']['review']['status'] = 'confirmed'
                state['ir']['review']['confirmed_at'] = _now()
            state['last_request'] = fingerprint
            version_file = Path(root)/'data/out/scenario_ir_drafts'/f"{scenario_id}-v{state['revision']}.json"
            state['file'] = str(version_file.relative_to(root))
            _atomic(version_file, state['ir'])
            event = _event(state, 'draft_confirmed' if confirm else 'input_decision_submitted')
            _atomic(path, state)
            _journal(root, state, event)
            return _response(state)
        except ValueError as error:
            # Rejections are journalled without supplied values or mutated working state.
            persisted = json.loads(path.read_text(encoding='utf-8'))
            event = _event(persisted, 'input_decision_rejected', reason=type(error).__name__)
            _atomic(path, persisted)
            _journal(root, persisted, event)
            raise
