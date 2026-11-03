"""Deterministic validation of submitted candidates, not request completeness."""
import re
from copy import deepcopy


REFERENCE_KEYS = ('response_key', 'content_type', 'response_path', 'path_type', 'row_scope')


def issue(code, path, message, expected=None, actual=None, action='REVISE_MAPPING'):
    return dict(code=code, item_path=path, message=message, expected=expected,
                actual=actual, recovery=dict(action=action))


def row_scope(field):
    path = field.get('response_path') or ''
    row = re.match(r'^(.*?/rows/row)(?:/|$)', path)
    array = re.match(r'^(.*\[\*\])', path)
    return field.get('row_scope') or (row.group(1) if row else array.group(1) if array else None)


def normalize_candidate(candidate, schema):
    result = deepcopy(candidate)
    fields = {f['path']: f for f in schema.get('parameters', [])}
    for item in result['inputs']:
        definition = fields.get(item.get('parameter_path'), {})
        for key, value in [('field', definition.get('name')), ('type', definition.get('type')),
                           ('xml_path', definition.get('xmlPath'))]:
            if item.get(key) is None:
                item[key] = value
    for output in result['outputs']:
        # row_scope is derivable from the response path. Treat null as omitted,
        # but leave explicit values intact so incorrect scopes still fail.
        if output.get('row_scope') is None:
            output['row_scope'] = row_scope(output)
    return result


def json_type(value):
    return {str: 'string', int: 'integer', float: 'number', bool: 'boolean',
            list: 'array', dict: 'object', type(None): 'null'}.get(type(value), type(value).__name__)


def validate_mapping(tools, candidate, current, previous):
    errors, warnings = [], []
    def add(code, path, message, expected=None, actual=None):
        errors.append(issue(code, path, message, expected, actual))
    for key in ['inputs', 'outputs', 'bindings']:
        if not isinstance(candidate.get(key), list) or any(not isinstance(x, dict) for x in candidate[key]):
            add('INVALID_MAPPING_OUTPUT', '/'+key, '객체 배열이 필요합니다', 'array[object]', candidate.get(key))
    if errors:
        return dict(valid=False, errors=errors, warnings=[])
    fields = {f['path']: f for f in tools.schema(current['selected_api_id']).get('parameters', [])}
    seen, names, bindings = set(), set(), {}
    for index, binding in enumerate(candidate['bindings']):
        name = binding.get('binding_id')
        if not name or name in bindings:
            add('DUPLICATE_MAPPING', f'/bindings/{index}/binding_id', '고유한 Binding ID가 필요합니다', 'unique nonempty ID', name)
        bindings[name] = binding
    for index, item in enumerate(candidate['inputs']):
        base, path = f'/inputs/{index}', item.get('parameter_path')
        if path not in fields:
            add('PARAMETER_PATH_NOT_FOUND', base+'/parameter_path', '현재 API에 없는 파라미터 경로입니다', list(fields), path)
            continue
        if path in seen:
            add('DUPLICATE_MAPPING', base+'/parameter_path', '중복 입력 경로입니다', 'unique path', path)
        seen.add(path)
        field = fields[path]
        for key, expected in [('type', field.get('type')), ('xml_path', field.get('xmlPath'))]:
            if item.get(key) != expected:
                add('PARAMETER_METADATA_MISMATCH', base+'/'+key, 'Canonical 기술 정보와 다릅니다', expected, item.get(key))
        source, value = item.get('source'), item.get('value')
        origins = ['user_condition','schema','parameter_kb','previous_output','run_input','unresolved']
        if item.get('origin') not in origins:
            add('INPUT_SOURCE_MISMATCH', base+'/origin', '허용되지 않은 origin입니다', origins, item.get('origin'))
        if source not in ['fixed', 'bind', 'run_input', 'unresolved']:
            add('INPUT_SOURCE_MISMATCH', base+'/source', '허용되지 않은 source입니다', ['fixed','bind','run_input','unresolved'], source)
        if source == 'fixed':
            typ, actual = field.get('type'), json_type(value)
            if value is None or not (typ == actual or typ == 'number' and actual == 'integer'):
                add('VALUE_TYPE_MISMATCH', base+'/value', '값 타입이 요청 타입과 다릅니다', typ, dict(type=actual, value=value))
            if field.get('enum') and value not in field['enum']:
                add('VALUE_ENUM_MISMATCH', base+'/value', '허용된 enum 값이 아닙니다', field['enum'], value)
            if not item.get('evidence'):
                add('EVIDENCE_MISMATCH', base+'/evidence', '고정값 근거가 없습니다', 'source evidence', [])
        elif value is not None:
            add('INPUT_SOURCE_MISMATCH', base+'/value', '실행 전 값은 null이어야 합니다', None, value)
        if source == 'bind':
            binding = bindings.get(item.get('ref'))
            if not binding or binding.get('to_parameter_path') != path:
                add('BINDING_TARGET_MISMATCH', base+'/ref', '입력 ref와 Binding 목적 경로가 연결되지 않습니다',
                    [b['binding_id'] for b in candidate['bindings'] if b.get('to_parameter_path') == path], item.get('ref'))
        elif item.get('ref') is not None:
            add('INPUT_SOURCE_MISMATCH', base+'/ref', 'bind 이외의 ref는 null이어야 합니다', None, item.get('ref'))
        if source in ['unresolved', 'run_input']:
            if not (item.get('reason') or '').strip():
                add('INVALID_UNRESOLVED', base+'/reason', '미해결 사유가 필요합니다', 'nonempty reason', item.get('reason'))
            warnings.append(dict(parameter_path=path, reason=item.get('reason')))
    active = []
    if candidate['outputs']:
        response = tools.read('get_response_outputs', current['selected_api_id'])
        active = [{**f, 'row_scope': row_scope(f)} for f in response.get('data', {}).get('outputs', [])]
    for index, output in enumerate(candidate['outputs']):
        base = f'/outputs/{index}'
        if not output.get('name') or output['name'] in names:
            add('DUPLICATE_MAPPING', base+'/name', '고유한 출력 이름이 필요합니다', 'unique nonempty name', output.get('name'))
        names.add(output.get('name'))
        keys = (*REFERENCE_KEYS, 'type')
        if not any(all(output.get(k) == f.get(k) for k in keys) for f in active):
            relevant = [f for f in active if f.get('name') == output.get('name')
                        or f.get('response_path') == output.get('response_path')]
            add('OUTPUT_DEFINITION_MISMATCH', base, '활성 응답 정의와 다릅니다',
                [{k: f.get(k) for k in keys} for f in (relevant or active)],
                {k: output.get(k) for k in keys})
        if not output.get('evidence'):
            add('EVIDENCE_MISMATCH', base+'/evidence', '출력 근거가 없습니다', 'source evidence', [])
    scopes = {}
    for index, binding in enumerate(candidate['bindings']):
        base, ref = f'/bindings/{index}', binding.get('from', {})
        outputs = previous.get(ref.get('from_step_id'), {}).get('outputs', [])
        output = next((o for o in outputs if o.get('name') == ref.get('output_name')), None)
        if not output or any(output.get(k) != ref.get(k) for k in REFERENCE_KEYS):
            add('BINDING_SOURCE_MISMATCH', base+'/from', '확인된 선행 출력 참조와 다릅니다',
                output or outputs or None, ref)
        destination = fields.get(binding.get('to_parameter_path'))
        connected = any(i.get('parameter_path') == binding.get('to_parameter_path') and
                        i.get('source') == 'bind' and i.get('ref') == binding.get('binding_id') for i in candidate['inputs'])
        if not destination or not connected:
            add('BINDING_TARGET_MISMATCH', base+'/to_parameter_path', 'Binding이 실제 입력과 연결되지 않습니다',
                [i.get('parameter_path') for i in candidate['inputs'] if i.get('source') == 'bind'], binding.get('to_parameter_path'))
        if output and destination and output.get('type') != destination.get('type'):
            add('BINDING_TYPE_MISMATCH', base, '출력·입력 타입이 다릅니다', destination.get('type'), output.get('type'))
        scopes.setdefault(ref.get('from_step_id'), set()).add(ref.get('row_scope'))
    if any(len(values) > 1 for values in scopes.values()):
        add('BINDING_SOURCE_MISMATCH', '/bindings', '같은 출처의 반복 행 범위가 다릅니다', 'same row_scope per source',
            {k: sorted(v, key=str) for k,v in scopes.items()})
    for section in ['inputs', 'outputs']:
        for index, item in enumerate(candidate[section]):
            for evidence_index, evidence in enumerate(item.get('evidence', [])):
                if not tools.evidence_valid(evidence, current=current, previous=previous):
                    add('EVIDENCE_MISMATCH', f'/{section}/{index}/evidence/{evidence_index}',
                        '기존 원문 근거 대조에 실패했습니다', 'existing source/pointer/quote', evidence)
    return dict(valid=not errors, errors=errors, warnings=warnings)
