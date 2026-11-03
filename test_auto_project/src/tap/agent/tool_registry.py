"""KB-first tools with material checks and an optional backend mapping gate."""
import json
import re
from copy import deepcopy

from .output_models import StepMappingResult
from .parameter_tools import MaterialError
from .mapping_validation import issue, normalize_candidate, row_scope, REFERENCE_KEYS

RELATED_STEP_SCORE_THRESHOLD = 0.7

READ_TOOLS = {
    'get_parameter_knowledge': '기본 조회: 자연어 조건을 매핑할 의미·별칭·지식과 schema(경로·타입·XML 위치)를 확인한다. 필수 여부는 판단하지 않는다.',
    'get_baseline_request': '조건부 조회: 기존 기본값·설정 자체의 해석이 필요할 때만 사용한다. 단순 대체 여부 비교는 백엔드가 수행한다.',
    'get_response_outputs': '조건부 조회: STEP 연결·최종 출력에 새 응답 필드 정의가 필요할 때 사용한다. previous_steps에 필요한 출력이 이미 있으면 생략할 수 있다.',
}


def spec(name, description, properties):
    return {'type': 'function', 'name': name, 'description': description, 'strict': True,
            'parameters': {'type': 'object', 'properties': properties,
                           'required': list(properties), 'additionalProperties': False}}


TOOLS = [spec(name, desc, {'selected_api_id': {'type': 'string'}}) for name, desc in READ_TOOLS.items()]
# Canonical and validate_mapping are backend-only; model tools stay the same.


class ToolRegistry:
    def __init__(self, tools, current, previous, errors, basic_tool='get_parameter_knowledge', validated=False, retriever=None, budget=None):
        self.tools, self.current, self.previous, self.errors = tools, current, previous, errors
        self.basic_tool = basic_tool
        self.results = {}  # STEP-local delivered results; not a cross-STEP cache.
        self.api = current['selected_api_id']
        self.incoming = current.get('input_dependencies', [])
        self.outgoing = current.get('output_consumers', [])
        self.relation_candidates = {row['step_id']: row for row in current.get('related_step_candidates', [])
                                    if isinstance(row, dict) and isinstance(row.get('step_id'), str)}
        self.related_step_selection = None
        self.output_patches = []
        self.allowed_outputs = {self.api} | {s['api']['api_id'] for s in previous.values()}
        self.validated = validated
        self.retriever, self.budget = retriever, budget
        self.delivered_paths = set()
        self.kb_stage = 'search'
        self.material_paths = []
        self.last_validation = None
        self.last_candidate = None

    @property
    def has_knowledge(self):
        return (self.basic_tool, self.api) in self.results

    @property
    def specs(self):
        specs = deepcopy(TOOLS if self.has_knowledge else [t for t in TOOLS if t['name'] == self.basic_tool])
        for tool in specs:
            allowed = sorted(self.pending_response_apis() or self.allowed_outputs) if tool['name'] == 'get_response_outputs' else [self.api]
            tool['parameters']['properties']['selected_api_id']['enum'] = allowed
            if self.retriever and tool['name'] == self.basic_tool:
                props = tool['parameters']['properties']
                props['scope'] = dict(type='string', enum=['search', 'expand', 'paths', 'full'],
                    description='search는 조건별 검색, expand는 k=10 확대, paths는 경로 상세, full은 전체 KB')
                props['parameter_paths'] = dict(type='array', items=dict(type='string'),
                    description='paths에서 조회할 전체 parameter_path. 나머지는 빈 배열')
                props['related_step_judgments'] = dict(type='array', items={
                    'type':'object', 'properties':{
                        'step_id':{'type':'string'}, 'score':{'type':'number'}, 'reason':{'type':'string'}},
                    'required':['step_id','score','reason'], 'additionalProperties':False},
                    description='입력 의존성이 없거나 모호할 때만 후보 STEP의 관련도 판단을 반환한다. 확정된 관계만 있으면 빈 배열')
                tool['parameters']['required'] = list(props)
        return specs

    @property
    def tool_choice(self):
        if not self.has_knowledge:
            return {'type': 'function', 'name': self.basic_tool}
        if self.pending_response_apis():
            return {'type': 'function', 'name': 'get_response_outputs'}
        return 'auto'

    def pending_response_apis(self):
        needed = {self.api} if self.outgoing else set()
        for dependency in self.incoming:
            source = self.previous.get(dependency['source_step_id'], {})
            if dependency.get('source_api_id') and not source.get('outputs'):
                needed.add(dependency['source_api_id'])
        return {api for api in needed if ('get_response_outputs', api) not in self.results}

    def _explicit_related_steps(self):
        selected = {}
        for dependency in self.incoming:
            step_id = dependency.get('source_step_id')
            if dependency.get('status') == 'resolved' and step_id:
                selected[step_id] = dict(step_id=step_id, basis='input_dependency')
        for dependency in self.outgoing:
            sequence = dependency.get('consumer_task_sequence')
            for step_id, step in self.relation_candidates.items():
                if sequence is not None and step.get('task_sequence') == sequence:
                    selected[step_id] = dict(step_id=step_id, basis='output_consumer')
        return selected

    @property
    def needs_related_step_judgment(self):
        ambiguous = any(dependency.get('status') != 'resolved' for dependency in self.incoming)
        return bool(self.retriever and self.relation_candidates and
                    (ambiguous or not self._explicit_related_steps()))

    @property
    def relation_judgment_candidates(self):
        ambiguous_ids = {step_id for dependency in self.incoming if dependency.get('status') != 'resolved'
                         for step_id in dependency.get('candidate_source_step_ids', [])}
        if ambiguous_ids:
            allowed = ambiguous_ids & set(self.relation_candidates)
        else:
            allowed = set(self.relation_candidates)
        return [self.relation_candidates[step_id] for step_id in sorted(allowed)
                if step_id not in self._explicit_related_steps()]

    def _select_related_steps(self, judgments):
        if self.related_step_selection is not None:
            return deepcopy(self.related_step_selection)
        selected = self._explicit_related_steps()
        if self.needs_related_step_judgment:
            if not isinstance(judgments, list):
                raise ValueError('related_step_judgments는 배열이어야 합니다')
            allowed = {row['step_id'] for row in self.relation_judgment_candidates}
            seen = set()
            for item in judgments:
                if not isinstance(item, dict) or set(item) != {'step_id','score','reason'}:
                    raise ValueError('관련 STEP 판정은 step_id/score/reason 객체여야 합니다')
                step_id, score, reason = item['step_id'], item['score'], item['reason']
                if step_id not in allowed or step_id in seen:
                    raise ValueError('관련 STEP 판정에 허용되지 않은 STEP ID 또는 중복 ID가 있습니다')
                if isinstance(score, bool) or not isinstance(score, (int,float)) or not 0 <= score <= 1:
                    raise ValueError('관련 STEP score는 0~1 숫자여야 합니다')
                if not isinstance(reason, str) or not reason.strip():
                    raise ValueError('관련 STEP 판정 근거가 필요합니다')
                seen.add(step_id)
                if score >= RELATED_STEP_SCORE_THRESHOLD:
                    selected[step_id] = dict(step_id=step_id, basis='llm_judgment', score=score,
                                             reason=reason.strip())
        self.related_step_selection = []
        for step_id, judgment in selected.items():
            catalog = self.relation_candidates.get(step_id, {})
            if not catalog:
                continue
            self.related_step_selection.append({**{key:catalog.get(key) for key in
                ('step_id','task_sequence','edge','action','conditions','api_id')}, **judgment})
        return deepcopy(self.related_step_selection)

    def _confirmed_upstream(self, binding):
        origin = binding['from']
        prior = self.previous.get(origin['from_step_id'], {})
        api = prior.get('api', {}).get('api_id')
        response = self.results.get(('get_response_outputs', api), {})
        for field in response.get('data', {}).get('outputs', []):
            if any(origin.get(key) != field.get(key) for key in ['response_key','content_type','response_path','path_type']):
                continue
            path = field['response_path']
            row = re.match(r'^(.*?/rows/row)(?:/|$)', path)
            array = re.match(r'^(.*\[\*\])', path)
            scope = field.get('row_scope') or (row.group(1) if row else array.group(1) if array else None)
            if origin.get('row_scope') != scope:
                continue
            output = {key: field.get(key) for key in ['response_key','content_type','response_path','path_type','type']}
            output.update(name=origin['output_name'], row_scope=scope, evidence=[dict(source_id=response['source_id'],
                source_pointer=field['source_pointer']+'/response_path', quote=path)])
            return dict(step_id=origin['from_step_id'], output=output)
        return None

    def _dependency_feedback(self, candidate):
        covered = {dependency_id for item in candidate['unresolved'] if item['reason'].strip()
                   for dependency_id in item['dependency_ids']}
        missing = []
        for dependency in self.outgoing:
            if not candidate['outputs'] and dependency['dependency_id'] not in covered:
                missing.append(dict(**dependency, required_action='define_outputs'))
        for dependency in self.incoming:
            bindings = [b for b in candidate['bindings'] if b['from']['from_step_id'] == dependency['source_step_id']
                        and any(i['source']=='bind' and i['ref']==b['binding_id'] and i['parameter_path']==b['to_parameter_path']
                                for i in candidate['inputs'])]
            if not bindings and dependency['dependency_id'] not in covered:
                missing.append(dict(**dependency, required_action='define_binding' if dependency['source_step_id'] else 'resolve_source'))
        if missing:
            return {'error':self.errors['dependency_coverage'], 'dependencies':missing}
        return None

    def _binding_compatibility_feedback(self, candidate):
        fields = {field['path']: field for field in self.tools.schema(self.api).get('parameters', [])}
        resolved_sources = {dependency.get('source_step_id') for dependency in self.incoming
                            if dependency.get('status') == 'resolved' and dependency.get('source_step_id')}
        mismatches = []
        for binding in candidate.get('bindings', []):
            source = binding.get('from', {})
            if self.incoming and source.get('from_step_id') not in resolved_sources:
                mismatches.append(dict(binding_id=binding.get('binding_id'),
                    reason='확정된 입력 의존성의 선행 STEP이 아님', source_step_id=source.get('from_step_id'),
                    allowed_source_step_ids=sorted(resolved_sources)))
            step = self.previous.get(source.get('from_step_id'), {})
            output = next((item for item in step.get('outputs', [])
                           if item.get('name') == source.get('output_name')), None)
            if output is None and step:
                confirmed = self._confirmed_upstream(binding)
                output = confirmed.get('output') if confirmed else None
            destination = fields.get(binding.get('to_parameter_path'))
            if not step:
                mismatches.append(dict(binding_id=binding.get('binding_id'),
                    reason='선행 STEP 식별자를 확인할 수 없음', source_step_id=source.get('from_step_id')))
            elif output is None:
                mismatches.append(dict(binding_id=binding.get('binding_id'),
                    reason='선행 STEP에서 확인된 출력이 없음', source_step_id=source.get('from_step_id'),
                    output_name=source.get('output_name')))
            if destination is None:
                mismatches.append(dict(binding_id=binding.get('binding_id'),
                    reason='후속 API에 존재하지 않는 입력 경로', target=binding.get('to_parameter_path')))
            elif output is not None and output.get('type') != destination.get('type'):
                mismatches.append(dict(binding_id=binding.get('binding_id'), reason='출력·입력 타입 불일치',
                    source_type=output.get('type'), target_type=destination.get('type')))
        if mismatches:
            return {'error':'STEP 연결 후보의 백엔드 검증에 실패했습니다', 'dependency_link_errors':mismatches}
        return None

    def apply_output_patches(self):
        for patch in self.output_patches:
            outputs = self.previous[patch['step_id']]['outputs']
            if not any(o['name']==patch['output']['name'] for o in outputs):
                outputs.append(deepcopy(patch['output']))
        return deepcopy(self.output_patches)

    def call_tool(self, name, arguments):
        try:
            args = json.loads(arguments)
            if not isinstance(args, dict):
                raise ValueError(self.errors['arguments'])
            if name == 'validate_mapping':
                raise ValueError(self.errors['disabled_validator'])
            if name not in READ_TOOLS:
                raise ValueError(self.errors['unknown_tool'])
            if not self.has_knowledge and name != self.basic_tool:
                raise ValueError(self.errors['incomplete'])
            api = args.get('selected_api_id')
            allowed = self.allowed_outputs if name == 'get_response_outputs' else {self.api}
            keys = {'selected_api_id', 'scope', 'parameter_paths', 'related_step_judgments'} if self.retriever and name == self.basic_tool else {'selected_api_id'}
            if api not in allowed or set(args) - keys:
                raise ValueError(self.errors['api_scope'])
            try:
                result = self.tools.read(name, selected_api_id=api)
                if self.retriever and name == self.basic_tool and not result.get('missing'):
                    scope = args.get('scope', self.kb_stage)
                    if scope not in ('search', 'expand', 'paths', 'full'):
                        raise ValueError('허용되지 않은 KB 조회 scope입니다')
                    paths = args.get('parameter_paths', self.material_paths)
                    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
                        raise ValueError('parameter_paths는 문자열 배열이어야 합니다')
                    related_steps = self._select_related_steps(args.get('related_step_judgments', []))
                    result = self.retriever.select(result, self.tools.schema(api),
                        self.current.get('intent_task', {}).get('conditions'), scope, paths, self.budget,
                        original_question=self.tools.documents.get('approved', {}).get('original_question'),
                        selection_reason=self.current.get('selection_reason'), related_steps=related_steps,
                        related_step_threshold=RELATED_STEP_SCORE_THRESHOLD if self.needs_related_step_judgment else None)
                    self.kb_stage = 'full' if result['retrieval']['fallback_reason'] or scope == 'full' else scope
                    self.delivered_paths.update(p['identity']['parameter_path'] for p in result['data']['parameters'])
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
                if self.validated:
                    return {'error': self.errors['artifact_read'].format(e=error), 'fatal': True}
                raise
            if result.get('missing') or result.get('error'):
                return {'error': self.errors['material_missing'].format(tool=name, api=api), 'fatal': True}
            self.results[name, api] = deepcopy(result)
            return result
        except MaterialError as error:
            return {'error': str(error), 'fatal': True}
        except (ValueError, TypeError, KeyError) as error:
            return {'error': self.errors['tool'].format(e=error)}

    def material_summary(self):
        return [{'tool': name, 'selected_api_id': api, 'source_id': result.get('source_id')}
                for (name, api), result in self.results.items()]

    def _normalize_output_evidence(self, candidate):
        response = self.results.get(('get_response_outputs', self.api))
        if not response or not response.get('source_id'):
            return
        fields = response.get('data', {}).get('outputs', [])
        for output in candidate['outputs']:
            matches = [field for field in fields
                       if field.get('name') == output.get('name')
                       and all(output.get(key) == (row_scope(field) if key == 'row_scope' else field.get(key))
                               for key in (*REFERENCE_KEYS, 'type'))]
            if len(matches) != 1:
                continue
            field = matches[0]
            pointer = field.get('source_pointer')
            if not pointer:
                continue
            # The backend can cite the exact response definition it just
            # matched. Replace model-authored citations to this same artifact,
            # which may combine fields into prose not present verbatim in JSON.
            evidence = [item for item in output.get('evidence', [])
                        if item.get('source_id') != response['source_id']]
            evidence.append(dict(source_id=response['source_id'],
                                 source_pointer=pointer + '/response_path',
                                 quote=field['response_path']))
            output['evidence'] = evidence

    def finish(self, content):
        self.last_validation = None
        self.last_candidate = None
        try:
            candidate = StepMappingResult.model_validate_json(content or '').model_dump(mode='json', by_alias=True)
            if self.validated:
                candidate = normalize_candidate(candidate, self.tools.schema(self.api))
            self.last_candidate = candidate
            if candidate['step_id'] != self.current['step_id'] and not self.validated:
                raise ValueError(self.errors['step_id'])
            if not self.has_knowledge:
                return None, {'error': self.errors['incomplete'], 'needed_tools': [self.basic_tool]}
            if candidate['assertions'] and not self.validated:
                raise ValueError(self.errors['assertions'])
            self.output_patches = []
            if self.retriever:
                missing = {i.get('parameter_path') for i in candidate['inputs']} - self.delivered_paths - {None}
                # Detect references to original KB/schema fields that were never
                # delivered, even if the candidate uses them only as evidence.
                kb = self.tools.records.get((self.basic_tool, self.api))
                canonical = self.tools.records.get(('get_request_schema', self.api))
                references = []
                needs_full = False
                def collect_evidence(value):
                    if isinstance(value, dict):
                        references.extend(value.get('evidence', []))
                        for child in value.values(): collect_evidence(child)
                    elif isinstance(value, list):
                        for child in value: collect_evidence(child)
                collect_evidence(candidate)
                for evidence in references:
                    for pair, identity_key in ((kb, 'identity'), (canonical, None)):
                        if not pair or evidence.get('source_id') != pair[1]: continue
                        if evidence.get('source_pointer') in ('', '/parameters') and len(self.delivered_paths) < len(pair[0].get('parameters', [])):
                            needs_full = True
                        match = re.match(r'^/parameters/(\d+)(?:/|$)', evidence.get('source_pointer') or '')
                        if match:
                            fields = pair[0].get('parameters', [])
                            index = int(match.group(1))
                            if index < len(fields):
                                field = fields[index]
                                path = field.get('identity', {}).get('parameter_path') if identity_key else field.get('path')
                                if path not in self.delivered_paths: missing.add(path)
                valid_paths = {f['path'] for f in self.tools.schema(self.api).get('parameters', [])}
                missing &= valid_paths
                if needs_full:
                    self.kb_stage = 'full'
                    return None, dict(error=self.errors['materials'], needed_materials=[dict(
                        tool=self.basic_tool, selected_api_id=self.api, scope='full', parameter_paths=[])])
                if missing:
                    self.material_paths = sorted(missing)
                    self.kb_stage = 'paths'
                    return None, dict(error=self.errors['materials'], needed_materials=[dict(
                        tool=self.basic_tool, selected_api_id=self.api, scope='paths', parameter_paths=self.material_paths)])
            needed = {('get_response_outputs', api) for api in self.pending_response_apis()}
            if candidate['outputs'] and ('get_response_outputs', self.api) not in self.results:
                needed.add(('get_response_outputs', self.api))
            # Baseline-derived evidence requires a Baseline actually supplied to this STEP.
            baseline_sources = {x['source_id']: x['selected_api_id'] for x in self.tools.sources if x['kind'] == 'baseline'}
            def evidence_dependencies(value):
                if isinstance(value, dict):
                    for evidence in value.get('evidence', []):
                        api = baseline_sources.get(evidence.get('source_id'))
                        if api and api != self.api:
                            raise ValueError(self.errors['api_scope'])
                        if api and ('get_baseline_request', api) not in self.results:
                            needed.add(('get_baseline_request', api))
                    for child in value.values(): evidence_dependencies(child)
                elif isinstance(value, list):
                    for child in value: evidence_dependencies(child)
            evidence_dependencies(candidate)
            missing_outputs = []
            for binding in candidate['bindings']:
                origin = binding['from']
                prior = self.previous.get(origin['from_step_id'], {})
                output = next((o for o in prior.get('outputs', []) if o['name'] == origin['output_name']), None)
                if output is not None and any(output.get(k) != origin.get(k) for k in
                        ['response_key','content_type','response_path','path_type','row_scope']):
                    missing_outputs.append(origin)
                    continue
                if output is None:
                    api = prior.get('api', {}).get('api_id')
                    if api and ('get_response_outputs', api) not in self.results:
                        needed.add(('get_response_outputs', api))
                    else:
                        patch = self._confirmed_upstream(binding)
                        if patch:
                            existing = next((p for p in self.output_patches if p['step_id']==patch['step_id']
                                             and p['output']['name']==patch['output']['name']), None)
                            if existing and existing['output'] != patch['output']:
                                missing_outputs.append(origin)
                            elif not existing:
                                self.output_patches.append(patch)
                        else:
                            missing_outputs.append(origin)
            if needed:
                return None, {'error': self.errors['materials'], 'needed_materials': [dict(tool=n, selected_api_id=a) for n,a in sorted(needed)]}
            link_feedback = self._binding_compatibility_feedback(candidate)
            if link_feedback:
                return None, link_feedback
            if missing_outputs:
                feedback = {'error': self.errors['previous_output'], 'missing_outputs': missing_outputs}
                if self.validated:
                    feedback['errors'] = [issue('BINDING_SOURCE_MISMATCH', '/bindings', self.errors['previous_output'],
                        self.previous.get(ref.get('from_step_id'), {}).get('outputs') or None, ref) for ref in missing_outputs]
                return None, feedback
            feedback = self._dependency_feedback(candidate)
            if feedback:
                if not self.validated:
                    return None, feedback
            if self.validated:
                self._normalize_output_evidence(candidate)
                staged = deepcopy(self.previous)
                for patch in self.output_patches:
                    staged[patch['step_id']]['outputs'].append(deepcopy(patch['output']))
                self.last_validation = self.tools.validate(candidate, self.current, staged)
                if not self.last_validation['valid']:
                    return None, {**self.last_validation, 'error': self.errors['repair']}
            return candidate, None
        except (ValueError, TypeError, KeyError) as error:
            feedback = {'error': self.errors['tool'].format(e=error)}
            if self.validated:
                feedback['errors'] = [issue('INVALID_MAPPING_OUTPUT', '/', str(error), 'StepMappingResult for '+self.current['step_id'], content)]
            return None, feedback
