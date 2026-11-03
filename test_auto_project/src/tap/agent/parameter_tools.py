"""Read-only artifact tools and the shared mapping validator."""
import json
import re
from copy import deepcopy
from pathlib import Path

class MaterialError(ValueError):
    """An artifact cannot be repaired by repeating a model tool request."""

class ParameterTools:
    folders = {'get_request_schema': 'canonical_schema', 'get_parameter_knowledge': 'parameter_kb/api',
               'get_baseline_request': 'baseline', 'get_response_outputs': 'response_outputs'}
    kinds = ['canonical_schema', 'parameter_knowledge', 'baseline', 'response_outputs']

    def __init__(self, root, approved, defer_optional_errors=False):
        self.root = Path(root)
        self.records, self.sources = {}, []
        self.used_source_ids = set()
        self.documents = {'approved': approved}
        self.record_errors, self.optional_errors = {}, {}
        common_path = self.root / 'data/out/parameters/parameter_kb/common/knowledge.json'
        self.common = []
        if common_path.is_file():
            common = json.loads(common_path.read_text(encoding='utf-8-sig'))
            self.common = [dict(record=x, source_pointer=f'/{i}') for i,x in enumerate(common) if x.get('status') == 'VERIFIED']
            self.documents['common-knowledge'] = common
            self.sources.append(dict(source_id='common-knowledge', kind='common_knowledge', selected_api_id=None, file=str(common_path.relative_to(self.root)), version=None))
        allowed = {r['selected_api_id'] for r in approved['api_selection_results']}
        for tool, folder in self.folders.items():
            for file in sorted((self.root / 'data/out/parameters' / folder).rglob('*.json')):
                try:
                    d = json.loads(file.read_text(encoding='utf-8-sig'))
                    if not isinstance(d, dict): raise ValueError('자료는 JSON 객체여야 합니다')
                except (ValueError, OSError) as error:
                    if defer_optional_errors and tool in ['get_baseline_request','get_response_outputs']:
                        self.optional_errors.setdefault(tool, []).append(f'{file.name}: {error}')
                        continue
                    raise
                sid = f"{d.get('document_id', d.get('documentId'))}:{d.get('api_id', d.get('apiId'))}"
                if sid not in allowed:
                    continue
                if (tool, sid) in self.records:
                    if defer_optional_errors and tool in ['get_baseline_request','get_response_outputs']:
                        self.record_errors[tool, sid] = f'중복 자료: {sid}'
                        continue
                    raise ValueError(f'중복 자료: {sid}')
                source = f'source-{len(self.sources)+1}'
                self.sources.append(dict(source_id=source, kind=self.kinds[list(self.folders).index(tool)], selected_api_id=sid,
                                         file=str(file.relative_to(self.root)), version=d.get('source', {}).get('documentVersion') if isinstance(d.get('source'), dict) else None))
                self.documents[source] = d
                self.records[tool, sid] = (d, source)

    def read(self, name, selected_api_id):
        if (name, selected_api_id) in self.record_errors:
            raise MaterialError(self.record_errors[name, selected_api_id])
        pair = self.records.get((name, selected_api_id))
        if not pair:
            if self.optional_errors.get(name):
                raise MaterialError('요청한 자료를 읽을 수 없습니다: ' + '; '.join(self.optional_errors[name]))
            return {'missing': True, 'selected_api_id': selected_api_id}
        d, source = pair
        self.used_source_ids.add(source)
        file = next(x['file'] for x in self.sources if x['source_id'] == source)
        # Preserve raw array offsets for JSON Pointer evidence.
        view = d
        if name == 'get_response_outputs':
            keys = ['name','response_key','content_type','response_path','path_type','type','description','enabled','is_active','review_required','response_kind','response_is_active','row_scope']
            view = {'outputs': [{**{k:o.get(k) for k in keys}, 'source_pointer':f'/outputs/{i}'}
                                for i,o in enumerate(d.get('outputs',[]))
                                if o.get('enabled') and o.get('is_active') and not o.get('review_required')
                                and o.get('response_kind') == 'SUCCESS' and o.get('response_is_active')]}
        elif name == 'get_parameter_knowledge':
            view = {'parameters': self._knowledge_parameters(d, selected_api_id, source),
                    'api_knowledge':[dict(record=p,source_pointer=f'/api_knowledge/{i}') for i,p in enumerate(d.get('api_knowledge',[])) if p.get('status')=='VERIFIED']}
        result = dict(source_id=source, source_file=file, source_pointer='', data=view)
        if name == 'get_parameter_knowledge':
            if 'common-knowledge' in self.documents:
                self.used_source_ids.add('common-knowledge')
            result['common_knowledge'] = dict(source_id='common-knowledge', records=self.common)
            result['notice'] = '추가 업무 지식은 VERIFIED만 적용한다. COMMON은 적용 범위가 맞는 것만 사용한다. 의미가 확인되지 않은 설명은 검증된 업무 규칙이 아니다.'
        return result

    def schema(self, api):
        pair = self.records.get(('get_request_schema', api), ({}, None))
        if pair[1]: self.used_source_ids.add(pair[1])
        return pair[0]

    @property
    def used_sources(self):
        return [x for x in self.sources if x['source_id'] in self.used_source_ids]

    def _knowledge_parameters(self, document, api, source):
        canonical, canonical_source = self.records.get(('get_request_schema', api), ({}, None))
        definitions = {f['path']: (i, f) for i, f in enumerate(canonical.get('parameters', []))}
        aliases = {'type':'type', 'enum':'enum', 'format':'format', 'xml_path':'xmlPath',
                   'xml_name':'xmlName', 'xml_attribute':'xmlAttribute'}
        result = []
        for i, item in enumerate(document.get('parameters', [])):
            identity = item.get('identity', {})
            identity_api = f"{identity.get('document_id', document.get('document_id'))}:{identity.get('api_id', document.get('api_id'))}"
            if identity_api != api:
                raise MaterialError('KB 파라미터의 API 식별 정보가 일치하지 않습니다: ' + identity_api)
            if identity.get('parameter_path') not in definitions:
                raise MaterialError('KB와 Canonical의 파라미터 경로가 일치하지 않습니다: ' + str(identity.get('parameter_path')))
            index, definition = definitions[identity['parameter_path']]
            schema = deepcopy(item.get('schema') or {})
            origins = {key: dict(source_id=source, source_pointer=f'/parameters/{i}/schema/{key}') for key in schema}
            for key, canonical_key in aliases.items():
                if schema.get(key) is None and definition.get(canonical_key) is not None:
                    schema[key] = deepcopy(definition[canonical_key])
                    origins[key] = dict(source_id=canonical_source, source_pointer=f'/parameters/{index}/{canonical_key}')
                    self.used_source_ids.add(canonical_source)
            result.append(dict(identity=deepcopy(identity), knowledge=deepcopy(item.get('knowledge')),
                               schema=schema, schema_sources=origins, provenance=deepcopy(item.get('provenance')),
                               source_pointer=f'/parameters/{i}'))
        return result

    @staticmethod
    def _evidence_leaf_strings(value):
        if isinstance(value, dict):
            return [text for child in value.values() for text in ParameterTools._evidence_leaf_strings(child)]
        if isinstance(value, list):
            return [text for child in value for text in ParameterTools._evidence_leaf_strings(child)]
        if isinstance(value, str):
            return [value]
        if value is None:
            return []
        return [str(value)]

    def evidence_valid(self, evidence, current=None, previous=None):
        try:
            source_id = evidence['source_id']
            d = self.documents[source_id]
            pointer = evidence['source_pointer']
            if pointer and not pointer.startswith('/'):
                return False
            # The LLM receives an approved-backed current_step projection. Allow
            # those exact prompt pointers against that projection, while raw
            # approved-file pointers continue to resolve against the source file.
            if source_id == 'approved' and current is not None and pointer == '/current_step':
                d, pointer = current, ''
            elif source_id == 'approved' and current is not None and pointer.startswith('/current_step/'):
                d, pointer = current, pointer[len('/current_step'):]
            # previous_steps is assembled by the runtime from already mapped
            # STEP outputs and is passed to the model as part of its context.
            # Resolve those citations against that exact snapshot rather than
            # the raw approved file, which does not contain runtime outputs.
            elif source_id == 'approved' and previous is not None and pointer == '/previous_steps':
                d, pointer = previous, ''
            elif source_id == 'approved' and previous is not None and pointer.startswith('/previous_steps/'):
                d, pointer = previous, pointer[len('/previous_steps'):]
            for token in pointer.split('/')[1:]:
                token = token.replace('~1', '/').replace('~0', '~')
                d = d[int(token)] if isinstance(d, list) else d[token]
            quote = evidence.get('quote', '')
            if not isinstance(quote, str) or not quote:
                return False
            if isinstance(d, str):
                return quote in d
            serialized = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
            if quote in serialized:
                return True
            leaves = self._evidence_leaf_strings(d)
            # A structured citation may summarize adjacent fields as
            # "field / description". Check each part against the pointed object
            # rather than relying on whitespace-sensitive JSON serialization.
            parts = [part.strip() for part in re.split(r'\s*/\s*', quote) if part.strip()]
            if len(parts) > 1:
                return all(any(part in leaf for leaf in leaves) for part in parts)
            return any(quote in leaf for leaf in leaves)
        except (KeyError, IndexError, TypeError, ValueError):
            return False

    def validate(self, candidate, current, previous):
        from .mapping_validation import validate_mapping
        return validate_mapping(self, candidate, current, previous)
