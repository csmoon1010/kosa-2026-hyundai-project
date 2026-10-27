"""실제 정책과 무관한 합성 fixture로 Parameter KB 저장/검토 계약을 검증한다."""
import json
import sqlite3
import tempfile
import unittest
import contextlib
import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import Mock, patch

# 노트북의 정의 셀만 읽어 기존 테스트에서 사용하며 실행/등록 셀은 수행하지 않는다.
def load_notebook_definitions():
    notebook = json.loads(Path(__file__).with_name('preprocessing.ipynb').read_text(encoding='utf-8'))
    module = ModuleType('parameter_kb_notebook_definitions')
    sys.modules[module.__name__] = module
    for index, cell in enumerate(notebook['cells']):
        if cell['cell_type'] == 'code' and cell.get('metadata', {}).get('parameter_kb_definition'):
            exec(compile(''.join(cell['source']), f'<notebook definitions {index}>', 'exec'), module.__dict__)
    return module


_kb_definitions = load_notebook_definitions()
ParameterKB = _kb_definitions.ParameterKB
ResponsesLLM = _kb_definitions.ResponsesLLM
WirePayload = _kb_definitions.WirePayload
ExtractionResult = _kb_definitions.ExtractionResult
MatchingResult = _kb_definitions.MatchingResult
strict_schema = _kb_definitions.strict_schema
CanonicalChromaIndex = _kb_definitions.CanonicalChromaIndex


# 실제 API 호출 없이 OpenAI 임베딩 요청과 검색 제어 흐름을 확인한다.
class FakeEmbeddingAPI:
    def __init__(self):
        self.inputs, self.requests = [], []

    def create(self, model, input, encoding_format, **kwargs):
        self.inputs.extend(input)
        self.requests.append({'model': model, 'input': input, 'encoding_format': encoding_format, **kwargs})
        vectors = [[1.0, 0.0] if ('수취인' in text or '물건을 받을 사람' in text) else [0.0, 1.0] for text in input]
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=v) for i, v in enumerate(vectors)])


# Chroma의 get/upsert/delete/query 입력과 API 필터를 검증하는 메모리 대역이다.
class FakeChromaCollection:
    def __init__(self):
        self.rows, self.queries = {}, []

    def _matches(self, metadata, where):
        if '$and' in where:
            return all(self._matches(metadata, item) for item in where['$and'])
        return all(metadata.get(key) in value['$in'] if isinstance(value, dict) else metadata.get(key) == value
                   for key, value in where.items())

    def get(self, where, include):
        rows = [(key, value) for key, value in self.rows.items() if self._matches(value['metadata'], where)]
        return {'ids': [key for key, _ in rows], 'metadatas': [value['metadata'] for _, value in rows]}

    def upsert(self, ids, embeddings, documents, metadatas):
        for key, vector, document, metadata in zip(ids, embeddings, documents, metadatas):
            self.rows[key] = {'vector': vector, 'document': document, 'metadata': metadata}

    def delete(self, ids):
        for key in ids:
            self.rows.pop(key, None)

    def query(self, query_embeddings, where, n_results, include):
        self.queries.append(where)
        scored = sorted([(1 - sum(a * b for a, b in zip(query_embeddings[0], value['vector'])), key, value)
                         for key, value in self.rows.items() if self._matches(value['metadata'], where)], key=lambda x: x[0])[:n_results]
        return {'ids': [[key for _, key, _ in scored]],
                'metadatas': [[value['metadata'] for _, _, value in scored]],
                'distances': [[distance for distance, _, _ in scored]]}


# API 키 없이 문서 추출/매칭 및 실패 응답을 재현한다.
class FakeLLM:
    # 합성 기본값 문서에서 추출 결과를 만들도록 설정한다.
    def __init__(self, invalid_quote=False, matching=False, failure=False):
        self.model, self.records = 'synthetic-test-only', []
        self.invalid_quote, self.matching, self.failure = invalid_quote, matching, failure

    # 실제 API 호출 대신 구조화 응답을 반환한다.
    def call(self, stage, instructions, payload, output_model):
        self.records.append({'stage': stage, 'input_tokens': 10, 'output_tokens': 5,
                             'total_tokens': 15, 'elapsed_seconds': 0.01})
        if self.failure:
            raise TimeoutError('synthetic timeout')
        if stage == 'parameter_matching':
            candidate = payload['candidates_by_ref']['subject'][0]
            return {'status': 'MATCHED', 'reason': 'fixture', 'matches': [
                {'ref_id': 'subject', 'candidate_id': candidate['candidate_id'], 'score': 0.99, 'reason': 'fixture'}]}
        chunk = payload['chunk']
        if chunk['text'].strip() == 'empty':
            return {'items': [], 'unresolved': []}
        value = '02' if '02' in chunk['text'] else '01'
        wire = {key: None for key in WirePayload.model_fields}
        wire['value'] = {'type': 'string', 'string': value, 'number': None, 'boolean': None}
        result = {'items': [{'kind': 'DEFAULT_VALUE', 'payload': wire,
                  'concept_refs': [{'ref_id': 'subject', 'term': '상품코드', 'role': 'SUBJECT', 'terms': []}],
                  'quote': 'invented' if self.invalid_quote else chunk['text'].strip(),
                  'chunk_id': chunk['chunk_id'], 'confidence': 0.99}], 'unresolved': []}
        return ExtractionResult.model_validate(result).model_dump()


# 특정 API의 실패를 재현하며 이후 API 호출 여부를 추적한다.
class PerApiLLM(FakeLLM):
    def __init__(self, mode='NONE'):
        super().__init__()
        self.mode, self.api_calls = mode, []

    def call(self, stage, instructions, payload, output_model):
        if stage != 'parameter_matching':
            return super().call(stage, instructions, payload, output_model)
        api_id = payload['api_id']
        self.api_calls.append(api_id)
        self.records.append({'stage': stage})
        matches = [{'ref_id': ref, 'candidate_id': next(c['candidate_id'] for c in candidates
            if c['parameter_path'].endswith('code' if ref == 'subject' else 'amount')),
            'score': 0.99, 'reason': 'fixture'} for ref, candidates in payload['candidates_by_ref'].items()]
        if api_id == 'B':
            if self.mode == 'TIMEOUT':
                raise TimeoutError('synthetic B timeout')
            if self.mode in ('NONE', 'AMBIGUOUS'):
                return {'status': self.mode, 'matches': [], 'reason': 'fixture B unresolved'}
            if self.mode == 'MISSING_REF':
                matches = []
            if self.mode == 'OUTSIDE':
                matches[0]['candidate_id'] = 'not-a-candidate'
            if self.mode == 'LOW_SCORE':
                matches[0]['score'] = 0.2
        return {'status': 'MATCHED', 'matches': matches, 'reason': 'fixture'}


# 조건부 필수 규칙에서 한 참조만 실패시키고 다른 참조/API가 계속 진행되는지 확인한다.
class PartialRefLLM:
    def __init__(self, fail_ref='amount', mode='NONE'):
        self.fail_ref, self.mode, self.ref_calls = fail_ref, mode, []

    def call(self, stage, instructions, payload, output_model):
        if stage == 'knowledge_extraction':
            wire = {key: None for key in WirePayload.model_fields}
            wire.update(rule_type='REQUIRED_IF', target_ref='amount', description='synthetic conditional requirement',
                condition={'operator': 'EQ', 'ref': 'subject',
                    'values': [{'type': 'string', 'string': '01', 'number': None, 'boolean': None}], 'conditions': []})
            result = {'items': [{'kind': 'RULE', 'payload': wire,
                'concept_refs': [{'ref_id': 'subject', 'term': '상품코드', 'role': 'CONDITION', 'terms': []},
                                 {'ref_id': 'amount', 'term': '수량', 'role': 'TARGET', 'terms': []}],
                'quote': payload['chunk']['text'].strip(), 'chunk_id': payload['chunk']['chunk_id'], 'confidence': 0.99}],
                'unresolved': []}
            return ExtractionResult.model_validate(result).model_dump()
        api_id, ref_id = payload['api_id'], payload['requested_ref_id']
        self.ref_calls.append((api_id, ref_id))
        candidates = payload['candidates_by_ref'][ref_id]
        match = {'ref_id': ref_id, 'candidate_id': next(c['candidate_id'] for c in candidates
                 if c['parameter_path'].endswith('code' if ref_id == 'subject' else 'amount')),
                 'score': 0.99, 'reason': 'synthetic reference match'}
        if api_id == 'A' and ref_id == self.fail_ref:
            if self.mode == 'TIMEOUT':
                raise TimeoutError('synthetic reference timeout')
            if self.mode in ('NONE', 'AMBIGUOUS'):
                return {'status': self.mode, 'matches': [], 'reason': 'synthetic unresolved reference'}
            if self.mode == 'LOW_SCORE':
                match['score'] = 0.2
            elif self.mode == 'OUTSIDE':
                match['candidate_id'] = 'invented-id'
            elif self.mode == 'MISSING':
                return {'status': 'MATCHED', 'matches': [], 'reason': 'synthetic omitted reference'}
            elif self.mode == 'DUPLICATE':
                return {'status': 'MATCHED', 'matches': [match, match], 'reason': 'synthetic duplicate reference'}
        return {'status': 'MATCHED', 'matches': [match], 'reason': 'synthetic'}


# 입력 분기・멱등성・검토・개정 교체・조회 우선순위를 임시 DB에서 확인한다.
class ParameterKBTests(unittest.TestCase):
    # 각 테스트에 독립적인 Canonical/KB DB를 생성한다.
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.canonical = self.root / 'canonical.db'
        self.apis = []
        for api_id in ('A', 'B'):
            self.apis.append({'documentId': 'doc', 'apiId': api_id, 'summary': '상품',
                'requestBodyRequired': True, 'parameters': [
                    {'path': '$.body.code', 'name': 'code', 'location': 'body', 'type': 'string',
                     'description': '상품코드', 'enum': ['01', '02'], 'required': False,
                     'requiredDeclared': False, 'xmlPath': '/Root/code', 'example': '01'},
                    {'path': '$.body.amount', 'name': 'amount', 'location': 'body', 'type': 'integer',
                     'description': '수량', 'required': True, 'requiredDeclared': True}]})
        with sqlite3.connect(self.canonical) as db:
            db.execute('CREATE TABLE api_canonical_schema(document_id TEXT,api_id TEXT,canonical_json TEXT)')
            db.executemany('INSERT INTO api_canonical_schema VALUES(?,?,?)', [('doc', a['apiId'], json.dumps(a)) for a in self.apis])
        db.close()
        self.vector_index = CanonicalChromaIndex(self.root / 'vectors', model_name='text-embedding-3-small')
        self.vector_index._collection = FakeChromaCollection()
        self.vector_index._embedding_client = SimpleNamespace(embeddings=FakeEmbeddingAPI())
        self.kb = ParameterKB(self.root, canonical_db_path=self.canonical, vector_index=self.vector_index)
        self.kb.initialize_parameter_kb('doc')
        self.concepts = [{'ref_id': 'subject', 'term': '상품코드', 'role': 'SUBJECT'}]
        self.target = {'document_id': 'doc', 'api_id': 'A', 'parameter_path': '$.body.code', 'role': 'subject'}

    # 임시 데이터만 정리한다.
    def tearDown(self):
        self.temp.cleanup()

    # 반복되는 합성 수동 입력을 생성한다.
    def manual(self, value='01', api=False, scope=None, **extra):
        return self.kb.register_manual_knowledge('DEFAULT_VALUE', {'value': value}, scope or {'type': 'GLOBAL'},
            'fixture-author', 'fixture-reason', api_ids=['A'] if api else None,
            canonical_document_id='doc' if api else None, targets=[self.target] if api else None,
            concept_refs=self.concepts, **extra)['knowledge']

    # 후보를 명시적으로 채택한다.
    def approve(self, k):
        return self.kb.review_parameter_knowledge(k['knowledge_id'], 'VERIFIED', 'reviewer', 'fixture reviewed')

    # 합성 문서 입력을 파일로 준비한다.
    def document(self, text='상품코드 기본값 01', name='policy'):
        path = self.root / f'{name}.md'
        path.write_text(text, encoding='utf-8')
        return {'domain_document_id': name, 'path': path, 'application_scope': {'type': 'GLOBAL'}}

    # Canonical 변환과 지식·검토 이력 보존을 검증한다.
    def test_base_idempotency_and_review(self):
        k = self.approve(self.manual())
        report = self.kb.initialize_parameter_kb('doc')
        self.assertEqual(report['parameters'], 4)
        view = self.kb.get_parameter_kb('doc', 'A')
        code = next(p for p in view['parameters'] if p['identity']['parameter_name'] == 'code')
        self.assertEqual(code['schema']['required_state'], 'UNSPECIFIED')
        self.assertEqual(code['schema']['example'], '01')
        self.assertEqual(code['schema']['xml_path'], '/Root/code')
        self.assertEqual(self.kb.knowledge(k['knowledge_id'])['status'], 'VERIFIED')
        self.assertEqual(len(self.kb.review_history(k['knowledge_id'])), 1)
        with self.kb.connect() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, {'parameter_kb', 'parameter_knowledge', 'kb_review'})

    # COMMON 등록이 Canonical을 조회하지 않으며 후보를 실행에 섞지 않는지 확인한다.
    def test_common_without_canonical(self):
        with patch.object(self.kb, 'canonical_apis', side_effect=AssertionError('COMMON must not search APIs')):
            k = self.manual()
            self.assertEqual(k['status'], 'CANDIDATE')
            self.assertEqual(self.kb.search_common_knowledge('상품코드'), [])
            self.approve(k)
            self.assertEqual(len(self.kb.search_common_knowledge('상품코드')), 1)
            repeated = self.manual()
            self.assertEqual(repeated['evidence_count'], 1)
            self.assertEqual(repeated['status'], 'VERIFIED')

    # 빈 API 목록과 COMMON 대상 혼합 및 잘못된 payload를 거부한다.
    def test_input_errors(self):
        for api_ids in ([], 'A', ['missing'], [None]):
            with self.assertRaises(ValueError):
                self.kb.registration_scope(api_ids, 'doc')
        with self.assertRaises(ValueError):
            self.kb.register_manual_knowledge('ALIAS', {'value': 'x'}, {'type': 'GLOBAL'}, 'a', 'r', concept_refs=self.concepts)
        with self.assertRaises(ValueError):
            self.kb.register_manual_knowledge('DEFAULT_VALUE', {'value': '01'}, {'type': 'GLOBAL'}, 'a', 'r', targets=[self.target], concept_refs=self.concepts)

    # API의 타입/enum 오류와 미해결 참조를 승인으로 우회하지 못하는지 확인한다.
    def test_api_validation(self):
        for value in (1, '99'):
            k = self.manual(value, api=True)
            self.assertEqual(k['status'], 'CONFLICT')
            with self.assertRaises(ValueError):
                self.approve(k)
        k = self.kb.register_manual_knowledge('DEFAULT_VALUE', {'value': '01'}, {'type': 'GLOBAL'},
            'a', 'r', api_ids=['A'], canonical_document_id='doc', concept_refs=self.concepts)['knowledge']
        self.assertEqual(k['status'], 'UNMATCHED')
        with self.assertRaises(ValueError):
            self.approve(k)


    # 상충하는 단일값은 보류하고 명시적인 보정만 별도 이력으로 채택한다.
    def test_conflict_and_manual_correction(self):
        original = self.approve(self.manual('01'))
        conflict = self.manual('02')
        self.assertEqual(conflict['status'], 'CONFLICT')
        with self.assertRaises(ValueError):
            self.approve(conflict)
        corrected = self.approve(self.manual('02', supersedes_id=original['knowledge_id']))
        self.assertEqual(self.kb._knowledge(False)[0]['knowledge_id'], corrected['knowledge_id'])
        self.assertEqual(self.kb.knowledge(original['knowledge_id'])['payload']['value'], '01')




    # 문서 API 지정 경로만 매칭 호출을 수행하는지 확인한다.
    def test_api_document_matching(self):
        spec = dict(self.document(), api_ids=['A'], canonical_document_id='doc')
        llm = FakeLLM()
        change = self.kb.enrich_parameter_kb([spec], llm=llm)[0]
        self.assertEqual(change['status'], 'READY_FOR_REVIEW', change)
        self.assertEqual([r['stage'] for r in llm.records], ['knowledge_extraction', 'parameter_matching'])
        for kid in change['knowledge_ids']:
            self.kb.review_parameter_knowledge(kid, 'VERIFIED', 'r', 'fixture')
        self.assertEqual(self.kb._knowledge(False)[0]['targets'][0]['api_id'], 'A')

    # 문자열이 겹치지 않는 필드도 의미 검색 결과로 들어오며 지정 API를 벗어나지 않는다.
    def test_chroma_semantic_candidate_and_api_filter(self):
        self.apis[0]['parameters'][0]['description'] = '수취인명'
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE api_canonical_schema SET canonical_json=? WHERE api_id='A'", (json.dumps(self.apis[0]),))
        db.close()
        result = self.kb.retrieve_parameter_candidates('doc', ['A'], '물건을 받을 사람', top_k=1)
        self.assertEqual(result[0]['parameter_path'], '$.body.code')
        self.assertEqual(result[0]['lexical_score'], 0)
        self.assertEqual(result[0]['semantic_rank'], 1)
        self.assertIsNone(result[0]['lexical_rank'])
        self.assertEqual({row['api_id'] for row in result}, {'A'})
        self.assertIn('물건을 받을 사람', self.vector_index._embedding_client.embeddings.inputs)

    # 환경변수 모델을 사용하고 문서/query에 접두어 없이 같은 API 요청 형식을 적용한다.
    def test_openai_embedding_model_and_payload(self):
        with patch.dict(os.environ, {'OPENAI_EMBEDDING_MODEL': 'text-embedding-3-small'}):
            index = CanonicalChromaIndex(self.root / 'vectors')
        api = FakeEmbeddingAPI()
        index._embedding_client = SimpleNamespace(embeddings=api)
        index._encode(['필드 설명: 수취인명'])
        index._encode(['물건을 받을 사람'])
        self.assertEqual(index.model_name, 'text-embedding-3-small')
        self.assertEqual([r['input'] for r in api.requests], [['필드 설명: 수취인명'], ['물건을 받을 사람']])
        self.assertTrue(all(r['model'] == 'text-embedding-3-small' and r['encoding_format'] == 'float' for r in api.requests))
        self.assertTrue(all('dimensions' not in r for r in api.requests))
        small_dimension = CanonicalChromaIndex(self.root / 'vectors', model_name=index.model_name, dimensions=2)
        small_dimension._embedding_client = SimpleNamespace(embeddings=api)
        small_dimension._encode(['차원 설정 확인'])
        self.assertEqual(api.requests[-1]['dimensions'], 2)
        self.assertNotEqual(index.collection_name, small_dimension.collection_name)

    # 변경 없는 재실행·별칭 승인/반려·Canonical 삭제가 인덱스에 반영된다.
    def test_chroma_incremental_index_and_approved_alias(self):
        self.assertEqual(self.kb.sync_parameter_index('doc', ['A'])['updated'], 2)
        self.assertEqual(self.kb.sync_parameter_index('doc', ['A'])['updated'], 0)
        alias = self.kb.register_manual_knowledge('ALIAS', {'value': '합성별칭', 'alias_type': 'NATURAL_LANGUAGE'},
            {'type': 'GLOBAL'}, 'a', 'fixture', api_ids=['A'], canonical_document_id='doc', targets=[self.target])['knowledge']
        self.assertEqual(self.kb.sync_parameter_index('doc', ['A'])['updated'], 0)
        self.approve(alias)
        self.assertEqual(self.kb.sync_parameter_index('doc', ['A'])['updated'], 1)
        self.kb.review_parameter_knowledge(alias['knowledge_id'], 'REJECTED', 'r', 'fixture')
        self.assertEqual(self.kb.sync_parameter_index('doc', ['A'])['updated'], 1)
        self.apis[0]['parameters'].pop()
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE api_canonical_schema SET canonical_json=? WHERE api_id='A'", (json.dumps(self.apis[0]),))
        db.close()
        self.assertEqual(self.kb.sync_parameter_index('doc', ['A'])['removed'], 1)

    # 각 API/참조의 후보를 따로 전달하고 누락·중복·후보 밖 매칭을 보류/거부한다.
    def test_llm_matches_each_api_and_concept(self):
        item = {'kind': 'DEPENDENCY', 'payload': {}, 'quote': '합성 근거', 'concept_refs': self.concepts + [
            {'ref_id': 'amount', 'term': '수량', 'role': 'TARGET', 'context': '구매 개수'}]}
        settings = {'api_ids': ['A', 'B'], 'canonical_document_id': 'doc'}
        llm = Mock()
        def matching(stage, instructions, payload, output_model):
            return {'status': 'MATCHED', 'reason': 'fixture', 'matches': [
                {'ref_id': ref, 'candidate_id': next(c['candidate_id'] for c in candidates
                 if c['parameter_path'].endswith('code' if ref == 'subject' else 'amount')),
                 'score': 0.99, 'reason': 'fixture'} for ref, candidates in payload['candidates_by_ref'].items()]}
        llm.call.side_effect = matching
        result = self.kb.match_parameter_knowledge(item, settings, llm)
        self.assertEqual(result['status'], 'CANDIDATE')
        self.assertEqual(len(result['targets']), 4)
        self.assertEqual(llm.call.call_count, 4)
        for call in llm.call.call_args_list:
            payload = call.args[2]
            self.assertEqual(set(payload['queries_by_ref']), {payload['requested_ref_id']})
            self.assertTrue(all(c['api_id'] == payload['api_id'] for cs in payload['candidates_by_ref'].values() for c in cs))
        def incomplete(stage, instructions, payload, output_model):
            response = matching(stage, instructions, payload, output_model)
            response['matches'] = []
            return response
        llm.call.side_effect = incomplete
        self.assertEqual(self.kb.match_parameter_knowledge(item, settings, llm)['status'], 'UNMATCHED')
        def duplicate(stage, instructions, payload, output_model):
            response = matching(stage, instructions, payload, output_model)
            response['matches'] = [response['matches'][0]] * 2
            return response
        llm.call.side_effect = duplicate
        self.assertEqual(self.kb.match_parameter_knowledge(item, settings, llm)['status'], 'AMBIGUOUS')
        def outside(stage, instructions, payload, output_model):
            response = matching(stage, instructions, payload, output_model)
            response['matches'][0]['candidate_id'] = 'invented-id'
            return response
        llm.call.side_effect = outside
        invalid = self.kb.match_parameter_knowledge(item, settings, llm)
        self.assertEqual(invalid['status'], 'UNMATCHED')
        self.assertEqual(len(invalid['api_results']), 2)
        self.assertTrue(all('error' in entry['details'] for entry in invalid['api_results']))

    # 중간 실패 뒤의 API까지 확인할 수 있도록 세 번째 합성 API를 추가한다.
    def add_third_api(self):
        third = json.loads(json.dumps(self.apis[0]))
        third['apiId'] = 'C'
        self.apis.append(third)
        with sqlite3.connect(self.canonical) as db:
            db.execute('INSERT INTO api_canonical_schema VALUES(?,?,?)', ('doc', 'C', json.dumps(third)))
        db.close()
        self.kb.initialize_parameter_kb('doc')

    # 미매칭·모호함·누락·오류·낮은 점수 모두 해당 API만 보류하고 다음 API로 진행한다.
    def test_partial_api_matching_continues(self):
        self.add_third_api()
        item = {'kind': 'DEPENDENCY', 'payload': {}, 'quote': 'synthetic', 'concept_refs': self.concepts + [
            {'ref_id': 'amount', 'term': '수량', 'role': 'TARGET'}]}
        settings = {'canonical_document_id': 'doc', 'api_ids': ['A', 'B', 'C']}
        for mode in ('NONE', 'AMBIGUOUS', 'TIMEOUT', 'MISSING_REF', 'OUTSIDE', 'LOW_SCORE'):
            with self.subTest(mode=mode):
                llm = PerApiLLM(mode)
                result = self.kb.match_parameter_knowledge(item, settings, llm)
                self.assertEqual(llm.api_calls, ['A', 'A', 'B', 'B', 'C', 'C'])
                self.assertEqual(result['status'], 'PARTIAL')
                self.assertEqual(len(result['targets']), 4)
                self.assertEqual({t['api_id'] for t in result['targets']}, {'A', 'C'})
                self.assertEqual([r['status'] for r in result['api_results']][::2], ['CANDIDATE', 'CANDIDATE'])
                self.assertEqual(result['api_results'][1]['targets'], [])
                expected = 'AMBIGUOUS' if mode in ('AMBIGUOUS', 'LOW_SCORE') else 'UNMATCHED'
                self.assertEqual(result['api_results'][1]['status'], expected)

    # 성공/보류를 별도 ID로 저장하고 성공한 API만 독립적으로 승인한다.
    def test_api_candidates_saved_and_reviewed_independently(self):
        self.add_third_api()
        spec = dict(self.document(), api_ids=['A', 'B', 'C'], canonical_document_id='doc')
        llm = PerApiLLM('TIMEOUT')
        result = self.kb.enrich_parameter_kb([spec], llm=llm)[0]
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(llm.api_calls, ['A', 'B', 'C'])
        self.assertEqual(len(result['knowledge_ids']), 3)
        outcomes = {r['api_id']: r for r in result['api_results']}
        self.assertEqual([outcomes[a]['status'] for a in ('A', 'B', 'C')], ['CANDIDATE', 'UNMATCHED', 'CANDIDATE'])
        for api_id, outcome in outcomes.items():
            knowledge = self.kb.knowledge(outcome['knowledge_id'])
            self.assertEqual(knowledge['api_ids'], [api_id])
            self.assertEqual(knowledge['matching'][0]['api_id'], api_id)
        with self.assertRaises(ValueError):
            self.kb.review_parameter_knowledge(outcomes['B']['knowledge_id'], 'VERIFIED', 'r', 'must fail')
        self.kb.review_parameter_knowledge(outcomes['A']['knowledge_id'], 'VERIFIED', 'r', 'fixture A verified')
        self.assertEqual([k['api_ids'] for k in self.kb._knowledge(False)], [['A']])
        repeated = self.kb.enrich_parameter_kb([spec], llm=PerApiLLM('TIMEOUT'))[0]
        self.assertEqual(set(repeated['knowledge_ids']), set(result['knowledge_ids']))
        self.assertTrue(all(self.kb.knowledge(kid)['evidence_count'] == 1 for kid in repeated['knowledge_ids']))
        self.assertEqual(self.kb.knowledge(outcomes['A']['knowledge_id'])['status'], 'VERIFIED')

    # 한 API의 Canonical 타입 충돌은 성공한 다른 API를 보류하지 않는다.
    def test_api_schema_conflict_is_isolated(self):
        self.add_third_api()
        self.apis[1]['parameters'][0].update(type='integer', enum=[1, 2])
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE api_canonical_schema SET canonical_json=? WHERE api_id='B'", (json.dumps(self.apis[1]),))
        db.close()
        spec = dict(self.document(), api_ids=['A', 'B', 'C'], canonical_document_id='doc')
        result = self.kb.enrich_parameter_kb([spec], llm=PerApiLLM('SUCCESS'))[0]
        self.assertEqual([r['status'] for r in result['api_results']], ['CANDIDATE', 'CONFLICT', 'CANDIDATE'])

    # 검색 예외와 저장 예외도 API 단위로 처리해 이후 API의 후보를 보존한다.
    def test_api_retrieval_and_save_failures_are_isolated(self):
        self.add_third_api()
        spec = dict(self.document(), api_ids=['A', 'B', 'C'], canonical_document_id='doc')
        retrieve = self.kb.retrieve_parameter_candidates
        def fail_b_search(document_id, api_ids, query, top_k):
            if api_ids == ['B']:
                raise RuntimeError('synthetic B search failure')
            return retrieve(document_id, api_ids, query, top_k)
        with patch.object(self.kb, 'retrieve_parameter_candidates', side_effect=fail_b_search):
            result = self.kb.enrich_parameter_kb([spec], llm=PerApiLLM('SUCCESS'))[0]
        self.assertEqual([r['status'] for r in result['api_results']], ['CANDIDATE', 'UNMATCHED', 'CANDIDATE'])
        save = self.kb._save
        def fail_b_save(db, knowledge, evidence):
            if knowledge['api_ids'] == ['B']:
                raise RuntimeError('synthetic B save failure')
            return save(db, knowledge, evidence)
        with patch.object(self.kb, '_save', side_effect=fail_b_save):
            result = self.kb.enrich_parameter_kb([spec], llm=PerApiLLM('SUCCESS'))[0]
        self.assertEqual([r['status'] for r in result['api_results']], ['CANDIDATE', 'ERROR', 'CANDIDATE'])
        self.assertEqual(len(result['knowledge_ids']), 2)

    # 같은 API의 일부 참조만 실패해도 나머지 Target과 이후 API 결과를 모두 반환한다.
    def test_reference_partial_success_preserves_targets(self):
        item = {'kind': 'RULE', 'payload': {}, 'quote': 'synthetic', 'concept_refs': self.concepts + [
            {'ref_id': 'amount', 'term': '수량', 'role': 'TARGET'}]}
        for failed_ref in ('subject', 'amount'):
            for mode in ('NONE', 'AMBIGUOUS', 'TIMEOUT', 'LOW_SCORE', 'OUTSIDE', 'MISSING', 'DUPLICATE'):
                with self.subTest(failed_ref=failed_ref, mode=mode):
                    llm = PartialRefLLM(failed_ref, mode)
                    result = self.kb.match_parameter_knowledge(item, {'canonical_document_id': 'doc', 'api_ids': ['A', 'B']}, llm)
                    self.assertEqual(llm.ref_calls, [('A', 'subject'), ('A', 'amount'), ('B', 'subject'), ('B', 'amount')])
                    self.assertEqual(result['status'], 'PARTIAL')
                    self.assertEqual(len(result['targets']), 3)
                    partial = result['api_results'][0]
                    self.assertEqual(partial['status'], 'PARTIAL')
                    self.assertEqual([t['role'] for t in partial['targets']], ['amount' if failed_ref == 'subject' else 'subject'])
                    self.assertEqual([r['ref_id'] for r in partial['details']['unresolved_refs']], [failed_ref])
                    self.assertEqual(result['api_results'][1]['status'], 'CANDIDATE')

    # 후보 없음/검색 오류도 그 참조만 보류하고 다른 참조의 LLM 매칭을 수행한다.
    def test_reference_retrieval_failure_is_isolated(self):
        retrieve = self.kb.retrieve_parameter_candidates
        item = {'kind': 'RULE', 'payload': {}, 'quote': 'synthetic', 'concept_refs': self.concepts + [
            {'ref_id': 'amount', 'term': '수량', 'role': 'TARGET'}]}
        for fail_ref, term in [('subject', '상품코드'), ('amount', '수량')]:
            for empty in (True, False):
                def retrieve_with_failure(document_id, api_ids, query, top_k):
                    if term in query:
                        if empty:
                            return []
                        raise RuntimeError('synthetic reference search failure')
                    return retrieve(document_id, api_ids, query, top_k)
                llm = PartialRefLLM(mode='SUCCESS')
                with patch.object(self.kb, 'retrieve_parameter_candidates', side_effect=retrieve_with_failure):
                    result = self.kb.match_parameter_knowledge(item, {'canonical_document_id': 'doc', 'api_ids': ['A']}, llm)
                self.assertEqual(result['status'], 'PARTIAL')
                self.assertEqual(len(result['targets']), 1)
                self.assertNotEqual(result['targets'][0]['role'], fail_ref)
                self.assertEqual(len(llm.ref_calls), 1)

    # 일부 Target을 SQLite에 보존하고 미해결 참조가 있는 지식의 승인은 거부한다.
    def test_partial_reference_storage_and_approval_guard(self):
        spec = dict(self.document('상품코드 01이면 수량 필수'), api_ids=['A', 'B'], canonical_document_id='doc')
        result = self.kb.enrich_parameter_kb([spec], llm=PartialRefLLM())[0]
        self.assertEqual([r['status'] for r in result['api_results']], ['PARTIAL', 'CANDIDATE'])
        partial_id, complete_id = [r['knowledge_id'] for r in result['api_results']]
        partial = self.kb.knowledge(partial_id)
        self.assertEqual([t['role'] for t in partial['targets']], ['subject'])
        self.assertEqual([r['ref_id'] for r in partial['matching'][0]['unresolved_refs']], ['amount'])
        with self.assertRaises(ValueError):
            self.kb.review_parameter_knowledge(partial_id, 'VERIFIED', 'r', 'must not approve')
        self.assertEqual(self.kb.review_history(partial_id), [])
        self.assertEqual(self.kb.knowledge(partial_id)['status'], 'PARTIAL')
        self.kb.review_parameter_knowledge(complete_id, 'VERIFIED', 'r', 'complete API independently reviewed')
        self.assertEqual([k['api_ids'] for k in self.kb._knowledge(False)], [['B']])
        frame = self.kb.knowledge_dataframe()
        row = frame[frame['knowledge_id'] == partial_id].iloc[0]
        self.assertEqual(row['matched_refs'], ['subject'])
        self.assertEqual([r['ref_id'] for r in row['unresolved_refs']], ['amount'])
        # 수동으로 모든 대상을 확인한 새 후보는 승인할 수 있으며 원본 부분 결과는 보존한다.
        targets = partial['targets'] + [{'document_id': 'doc', 'api_id': 'A', 'parameter_path': '$.body.amount', 'role': 'amount'}]
        corrected = self.kb.register_manual_knowledge(partial['kind'], partial['payload'], partial['application_scope'],
            'reviewer', 'missing target manually confirmed', api_ids=['A'], canonical_document_id='doc',
            targets=targets, concept_refs=partial['concept_refs'])['knowledge']
        self.assertEqual(self.approve(corrected)['status'], 'VERIFIED')
        self.assertEqual(self.kb.knowledge(partial_id)['status'], 'PARTIAL')

    # payload에 직접 쓰이지 않은 선언 ConceptRef도 해결되기 전에는 승인할 수 없다.
    def test_all_declared_references_are_required(self):
        concepts = self.concepts + [{'ref_id': 'extra', 'term': '수량', 'role': 'CONDITION'}]
        k = self.kb.register_manual_knowledge('DEFAULT_VALUE', {'value': '01'}, {'type': 'GLOBAL'},
            'a', 'r', api_ids=['A'], canonical_document_id='doc', targets=[self.target], concept_refs=concepts)['knowledge']
        self.assertEqual(k['status'], 'PARTIAL')
        with self.assertRaises(ValueError):
            self.approve(k)

    # COMMON 등록과 문서 추출은 Chroma 인덱스를 읽거나 생성하지 않는다.
    def test_common_skips_chroma_and_matching(self):
        with patch.object(self.vector_index, 'sync', side_effect=AssertionError('COMMON searched Canonical')):
            self.approve(self.manual())
            llm = FakeLLM()
            result = self.kb.enrich_parameter_kb([self.document()], llm=llm)[0]
            self.assertEqual(result['status'], 'READY_FOR_REVIEW')
            self.assertEqual([row['stage'] for row in llm.records], ['knowledge_extraction'])

    # Canonical 변경은 연결된 API 지식에만 재검증을 요구한다.
    def test_canonical_revalidation(self):
        api, common = self.approve(self.manual(api=True)), self.approve(self.manual())
        self.apis[0]['parameters'][0]['enum'] = ['01']
        with sqlite3.connect(self.canonical) as db:
            db.execute('UPDATE api_canonical_schema SET canonical_json=? WHERE api_id=?', (json.dumps(self.apis[0]), 'A'))
        db.close()
        self.kb.initialize_parameter_kb('doc', ['A'])
        self.assertEqual(self.kb.knowledge(api['knowledge_id'])['status'], 'REVALIDATION_REQUIRED')
        self.assertEqual(self.kb.knowledge(common['knowledge_id'])['status'], 'VERIFIED')

    # API 일부 재생성은 다른 API에 영향을 주지 않고 전체 재생성은 삭제된 API를 비활성화한다.
    def test_deleted_api_and_partial_regeneration(self):
        self.approve(self.manual(api=True))
        with sqlite3.connect(self.canonical) as db:
            db.execute("DELETE FROM api_canonical_schema WHERE api_id='A'")
        db.close()
        self.assertEqual(self.kb.initialize_parameter_kb('doc', ['B'])['removed'], 0)
        self.assertEqual(self.kb.initialize_parameter_kb('doc')['removed'], 2)
        with self.kb.connect() as db:
            self.assertEqual(db.execute("SELECT sum(active) FROM parameter_kb WHERE api_id='A'").fetchone()[0], 0)

    # JSON/표 산출물을 임시 경로에서 생성한다.
    def test_export_and_dataframe(self):
        self.approve(self.manual())
        paths = self.kb.export_parameter_kb('doc')
        self.assertEqual(len(paths), 3)
        self.assertTrue(all(Path(p).is_file() for p in paths))
        self.assertEqual(len(self.kb.knowledge_dataframe()), 5)


    # 의존성의 모든 참조와 조건 깊이를 검증한다.
    def test_dependency_and_condition_depth(self):
        concepts = self.concepts + [{'ref_id': 'amount', 'term': '수량', 'role': 'TARGET'}]
        payload = {'condition': {'operator': 'EQ', 'ref': 'subject', 'value': '01'}, 'target_ref': 'amount',
                   'constraint': {'rule_type': 'MIN_VALUE', 'constraint': 1, 'target_ref': 'amount', 'description': 'fixture'},
                   'description': 'fixture dependency'}
        k = self.kb.register_manual_knowledge('DEPENDENCY', payload, {'type': 'GLOBAL'}, 'a', 'r',
            api_ids=['A'], canonical_document_id='doc', targets=[self.target], concept_refs=concepts)['knowledge']
        self.assertEqual(k['status'], 'PARTIAL')
        payload['condition'] = {'operator': 'AND', 'conditions': [payload['condition'], payload['condition']]}
        payload['condition'] = {'operator': 'AND', 'conditions': [payload['condition'], payload['condition']]}
        payload['condition'] = {'operator': 'AND', 'conditions': [payload['condition'], payload['condition']]}
        with self.assertRaises(ValueError):
            self.kb.register_manual_knowledge('DEPENDENCY', payload, {'type': 'GLOBAL'}, 'a', 'r', concept_refs=concepts)


    # 파일 형식과 범위 설정을 검증하고 정확한 API 대상만으로 수동 등록한다.
    def test_file_scope_and_target_only_registration(self):
        spec = dict(self.document(), path=self.root / 'unsupported.pdf')
        with self.assertRaises(ValueError):
            self.kb.load_domain_document(spec)
        with self.assertRaises(ValueError):
            self.manual(scope={'type': 'EDGE', 'domain_id': 'd'})
        k = self.kb.register_manual_knowledge('DEFAULT_VALUE', {'value': '01'}, {'type': 'GLOBAL'},
            'a', 'r', api_ids=['A'], canonical_document_id='doc', targets=[self.target])['knowledge']
        self.assertEqual(k['status'], 'CANDIDATE')

    # 기존 Canonical을 임시 경로에 복사하여 노트북 3단계 기본 실행 전체를 확인한다.
    def test_notebook_stage3_with_existing_canonical(self):
        project = Path(__file__).parent
        existing = project / 'output' / 'canonical_schema.db'
        if not existing.is_file():
            self.skipTest('저장된 Canonical DB가 없습니다.')
        copied = self.root / 'existing_canonical.db'
        copied.write_bytes(existing.read_bytes())
        with contextlib.closing(sqlite3.connect(copied)) as db:
            doc_id = db.execute('SELECT document_id FROM api_canonical_schema LIMIT 1').fetchone()[0]
            expected = sum(len(json.loads(r[0])['parameters']) for r in db.execute(
                'SELECT canonical_json FROM api_canonical_schema WHERE document_id=?', (doc_id,)))
        nb = json.loads((project / 'preprocessing.ipynb').read_text(encoding='utf-8'))
        env = dict(vars(_kb_definitions), PROJECT_DIR=self.root, DB_PATH=copied,
                   DOCUMENT_ID=doc_id, OUTPUT_DIR=self.root / 'output', display=lambda *args: None)
        with patch.dict(os.environ, {'OPENAI_EMBEDDING_MODEL': 'text-embedding-3-small'}), contextlib.redirect_stdout(io.StringIO()):
            for c in nb['cells'][24:]:
                # 새 4번 절의 실행 셀은 Parameter KB 검증에 포함하지 않는다.
                if c.get('id') == 'response-outputs-title':
                    break
                if c['cell_type'] == 'code' and not c.get('metadata', {}).get('parameter_kb_definition'):
                    exec(compile(''.join(c['source']), '<stage3 notebook>', 'exec'), env)
        self.assertEqual(env['kb_base_report']['parameters'], expected)
        print(f'\nActual Canonical smoke: {env["kb_base_report"]}')


    # LLM 스키마의 모든 객체가 strict의 required/additionalProperties 계약을 만족한다.
    def test_structured_output_schema(self):
        # 재귀 참조를 따라가지 않고 생성된 JSON 노드를 순회한다.
        def visit(node):
            if isinstance(node, dict):
                if node.get('type') == 'object':
                    self.assertFalse(node['additionalProperties'])
                    self.assertEqual(set(node['required']), set(node['properties']))
                for child in node.values():
                    visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)
        visit(strict_schema(ExtractionResult))


if __name__ == '__main__':
    unittest.main()
