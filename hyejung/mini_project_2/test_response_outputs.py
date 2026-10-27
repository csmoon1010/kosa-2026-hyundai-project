"""Response Outputs의 실제 원본 추출과 SQLite 동기화 계약을 외부 호출 없이 검증한다."""
import copy
import json
import re
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


PROJECT = Path(__file__).parent


def load_definitions():
    notebook = json.loads((PROJECT / 'preprocessing.ipynb').read_text(encoding='utf-8'))
    module = ModuleType('response_output_definitions')
    for cell in notebook['cells']:
        if cell.get('metadata', {}).get('response_outputs_definition'):
            exec(compile(''.join(cell['source']), '<response outputs definitions>', 'exec'), module.__dict__)
    return module


impl = load_definitions()


def obj(**fields):
    return {'type': 'object', 'properties': fields}


def media(schema, content_type='application/json', description='success'):
    return {'description': description, 'content': {content_type: {'schema': schema}}}


def document():
    return {'openapi': '3.0.1', 'info': {'title': 'synthetic', 'version': '1'},
            'paths': {
                '/a': {'post': {'operationId': 'a', 'responses': {
                    '200': media(obj(id={'type': 'string'}, other={'type': 'integer'})),
                    '200_fail': media(obj(code={'type': 'string'}), description='실패 (Http Status Code는 200으로 응답)'),
                    'default': media(obj(detail={'type': 'string'})),
                }}},
                '/b': {'get': {'operationId': 'b', 'responses': {'200': media(obj(value={'type': 'boolean'}))}}},
            }, 'components': {'schemas': {}}}


def select_json(value, path):
    """테스트에서 생성 경로를 실제 샘플에 적용하는 최소 JSONPath 해석기."""
    tokens = re.findall(r'\.([A-Za-z_][A-Za-z0-9_]*)|\[("(?:\\.|[^"\\])*")\]|\[(\*)\]', path[1:])
    values = [value]
    for dot_name, quoted_name, star in tokens:
        if star:
            values = [item for array in values for item in array]
        else:
            key = dot_name or json.loads(quoted_name)
            values = [item[key] for item in values]
    return values


class ResponseOutputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'output').mkdir()
        self.doc = document()
        self.store = impl.ResponseOutputs(self.root)
        self.seed()

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self):
        self.store.raw_path.write_text(json.dumps(self.doc, ensure_ascii=False, indent=2), encoding='utf-8')
        with sqlite3.connect(self.store.canonical_db_path) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS api_canonical_schema '
                         '(document_id TEXT,api_id TEXT,method TEXT,endpoint TEXT,source_hash TEXT,source_url TEXT)')
            conn.execute('DELETE FROM api_canonical_schema')
            for endpoint, item in self.doc['paths'].items():
                for method, operation in item.items():
                    if isinstance(operation, dict) and 'responses' in operation:
                        conn.execute('INSERT INTO api_canonical_schema VALUES (?,?,?,?,?,?)',
                                     ('doc', impl.response_api_id(method, endpoint, operation), method.upper(), endpoint,
                                      impl.response_source_hash(self.doc), 'https://example.invalid/swagger'))

    def run_extract(self, api_ids=None):
        return self.store.initialize_response_outputs('doc', api_ids)

    def all_fields(self, api_id='a'):
        return self.store.get_response_outputs('doc', api_id, include_inactive=True, include_failures=True)

    def key(self, field):
        return {k: field[k] for k in ('document_id','api_id','response_key','content_type','schema_path')}

    def field(self, path='$.id', response_key='200'):
        return next(f for f in self.all_fields() if f['schema_path'] == path and f['response_key'] == response_key)

    def test_success_only_enabled_and_failure_http200(self):
        report = self.run_extract()
        self.assertEqual(report['failed_api_count'], 0)
        self.assertEqual(report['response_count'], 4)
        self.assertTrue(self.field()['enabled'])
        failure = self.field('$.code', '200_fail')
        self.assertEqual((failure['status_code'], failure['response_kind'], failure['enabled']), ('200', 'FAILURE', False))
        self.assertFalse(self.field('$.detail', 'default')['enabled'])
        self.assertEqual(len(self.store.get_response_outputs('doc', 'a')), 2)
        for field in [failure, self.field('$.detail', 'default')]:
            with self.assertRaises(ValueError):
                self.store.configure_response_output(self.key(field), True)

    def test_same_source_preserves_settings_and_timestamps(self):
        self.run_extract()
        original = self.field()
        self.store.configure_response_output(self.key(original), False, 'customId')
        second = self.run_extract()
        current = self.field()
        self.assertEqual(second['created'], 0)
        self.assertEqual(current['created_at'], original['created_at'])
        self.assertEqual((current['enabled'], current['name']), (False, 'customId'))
        self.assertEqual(len(self.all_fields()), 4)
        with sqlite3.connect(self.store.db_path) as conn:
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_type_change_requires_confirmation(self):
        self.run_extract()
        self.doc['paths']['/a']['post']['responses']['200']['content']['application/json']['schema']['properties']['id']['type'] = 'integer'
        self.seed()
        self.run_extract()
        current = self.field()
        self.assertTrue(current['review_required'])
        self.assertNotIn('$.id', [f['schema_path'] for f in self.store.get_response_outputs('doc', 'a')])
        self.store.configure_response_output(self.key(current), True, confirm_review=True)
        self.assertFalse(self.field()['review_required'])

    def test_new_fields_deletions_and_partial_scope(self):
        self.run_extract()
        props = self.doc['paths']['/a']['post']['responses']['200']['content']['application/json']['schema']['properties']
        del props['other']
        props['new'] = {'type': 'string'}
        self.seed()
        report = self.run_extract(['a'])
        self.assertEqual(report['deactivated'], 1)
        self.assertFalse(self.field('$.other')['is_active'])
        self.assertTrue(self.field('$.new')['enabled'])
        self.assertEqual(len(self.store.get_response_outputs('doc', 'b')), 1)

    def test_deleted_response_inactivates_fields(self):
        self.run_extract()
        del self.doc['paths']['/a']['post']['responses']['200_fail']
        self.seed()
        self.run_extract(['a'])
        failure = self.field('$.code', '200_fail')
        self.assertFalse(failure['is_active'])
        self.assertFalse(failure['response_is_active'])

    def test_partial_preserves_missing_fields_but_blocks_confirmation(self):
        self.run_extract()
        self.doc['paths']['/a']['post']['responses']['200']['content']['application/json']['schema'] = {'$ref': '#/missing'}
        self.seed()
        report = self.run_extract(['a'])
        self.assertEqual(report['api_results'][0]['status'], 'PARTIAL')
        field = self.field()
        self.assertTrue(field['is_active'])
        self.assertTrue(field['review_required'])
        with self.assertRaises(ValueError):
            self.store.configure_response_output(self.key(field), True, confirm_review=True)
        self.doc['paths']['/a']['post']['responses']['200']['content']['application/json']['schema'] = obj(id={'type': 'string'})
        self.seed()
        self.run_extract(['a'])
        self.store.configure_response_output(self.key(self.field()), True, confirm_review=True)
        self.assertFalse(self.field()['review_required'])

    def test_failed_api_rolls_back_and_later_api_continues(self):
        self.run_extract()
        previous = self.all_fields()
        real = self.store._persist_api
        def broken(conn, definitions, api, source_hash):
            counts = real(conn, definitions, api, source_hash)
            if api['api_id'] == 'a':
                raise RuntimeError('synthetic write failure')
            return counts
        with patch.object(self.store, '_persist_api', side_effect=broken):
            report = self.run_extract()
        self.assertEqual(report['failed_api_count'], 1)
        self.assertEqual([r['status'] for r in report['api_results']], ['FAILED', 'COMPLETE'])
        self.assertEqual(self.all_fields(), previous)
        self.assertEqual(report['updated'], 1)

    def test_hash_mismatch_prevents_output_database_creation(self):
        self.doc['info']['version'] = '2'
        self.store.raw_path.write_text(json.dumps(self.doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '불일치'):
            self.run_extract()
        self.assertFalse(self.store.db_path.exists())

    def test_api_identity_mismatch_and_missing_selection(self):
        with self.assertRaisesRegex(ValueError, '없는 API'):
            self.run_extract(['missing'])
        with sqlite3.connect(self.store.canonical_db_path) as conn:
            conn.execute("UPDATE api_canonical_schema SET method='GET' WHERE api_id='a'")
        with self.assertRaisesRegex(ValueError, '불일치'):
            self.run_extract()

    def test_memory_source_exclusive_and_fallback_api_id(self):
        del self.doc['paths']['/b']['get']['operationId']
        self.seed()
        self.assertEqual(self.run_extract(['get_b'])['failed_api_count'], 0)
        self.assertEqual(self.store.load_response_source(document_id='doc', raw_document=self.doc)[2],
                         impl.response_source_hash(self.doc))
        with self.assertRaises(ValueError):
            self.store.load_response_source(self.store.raw_path, 'doc', raw_document=self.doc)

    def test_nonstandard_uppercase_date_normalization(self):
        self.doc['paths']['/a']['post']['responses'] = {'200': media(obj(date={'type':'DATE'}))}
        self.seed()
        self.run_extract()
        field = self.field('$.date')
        self.assertEqual((field['type'], field['format']), ('string','date'))
        self.assertEqual(field['metadata']['raw_type'], 'DATE')
        self.assertFalse(field['review_required'])

    def test_description_and_required_metadata(self):
        schema = obj(code={'type': 'string', 'example': '코드(예:0001)'},
                     explicit={'type': 'integer', 'description': '명시 설명', 'example': '다른 설명(예:1)'})
        schema['required'] = ['code']
        self.doc['paths']['/a']['post']['responses'] = {'200': media(schema)}
        self.seed()
        self.run_extract()
        field = self.field('$.code')
        self.assertEqual(field['description'], '코드')
        self.assertEqual(field['metadata']['example'], '코드(예:0001)')
        self.assertTrue(field['metadata']['required_declared'])
        self.assertFalse(self.field('$.explicit')['metadata']['required'])
        self.assertTrue(self.field('$.explicit')['metadata']['required_declared'])

    def test_names_duplicate_and_manual_collision(self):
        self.doc['paths']['/a']['post']['responses'] = {'200': media(obj(
            left=obj(id={'type': 'string'}), right=obj(id={'type': 'string'})))}
        self.seed()
        self.run_extract()
        fields = self.all_fields()
        self.assertEqual(len({f['name'] for f in fields}), 2)
        self.assertTrue(all(f['name'].startswith('id_') for f in fields))
        with self.assertRaises(ValueError):
            self.store.configure_response_output(self.key(fields[0]), True, fields[1]['name'])

    def test_json_array_paths_match_sample(self):
        self.doc['paths']['/a']['post']['responses'] = {'200': media({
            'type': 'array', 'items': {'$ref': '#/components/schemas/Row'}})}
        self.doc['components']['schemas']['Row'] = obj(**{
            'odd.key': {'type': 'string'}, 'values': {'type': 'array', 'items': {'type': 'integer'}}})
        self.seed()
        self.run_extract()
        fields = self.all_fields()
        self.assertEqual(select_json([{'odd.key': 'x', 'values': [2, 3]}], '$[*]["odd.key"]'), ['x'])
        self.assertEqual(select_json([{'odd.key': 'x', 'values': [2, 3]}], '$[*].values[*]'), [2, 3])
        self.assertIn('$[*]["odd.key"]', [f['schema_path'] for f in fields])
        self.assertEqual(self.field('$[*].values[*]')['metadata']['cardinality'], 'MANY')

    def test_recursive_refs_and_reuse(self):
        self.doc['components']['schemas'] = {
            'Node': obj(value={'type': 'string'}, child={'$ref': '#/components/schemas/Node'}),
            'Leaf': obj(id={'type': 'string'}),
        }
        self.doc['paths']['/a']['post']['responses'] = {'200': media(obj(
            first={'$ref': '#/components/schemas/Leaf'}, second={'$ref': '#/components/schemas/Leaf'},
            node={'$ref': '#/components/schemas/Node'}, external={'$ref': 'https://example.invalid/external'}))}
        self.seed()
        report = self.run_extract()
        fields = {f['schema_path']: f for f in self.all_fields()}
        self.assertIn('$.first.id', fields)
        self.assertIn('$.second.id', fields)
        self.assertIn('$.node.value', fields)
        self.assertEqual(fields['$.first.id']['metadata']['source_ref'], '#/components/schemas/Leaf')
        warnings = report['api_results'][0]['responses'][0]['warnings']
        self.assertTrue({'CYCLIC_REF', 'UNRESOLVED_REF'}.issubset({w['code'] for w in warnings}))

    def test_allof_merge_conflicts_and_union(self):
        self.doc['paths']['/a']['post']['responses'] = {
            '200': media({'allOf': [obj(a={'type': 'string'}), obj(b={'type': 'integer'})]}),
            '201': media({'allOf': [obj(id={'type': 'string'}), obj(id={'type': 'integer'})]}),
            '202': media({'oneOf': [obj(x={'type': 'string'}), obj(y={'type': 'string'})]}),
        }
        self.seed()
        self.run_extract()
        self.assertEqual({f['schema_path'] for f in self.all_fields()}, {'$.a', '$.b'})
        definitions = self.store.get_response_definitions('doc', 'a')
        self.assertEqual([d['extraction_status'] for d in definitions], ['COMPLETE','PARTIAL','PARTIAL'])
        self.assertEqual(definitions[1]['warnings'][0]['code'], 'ALLOF_CONFLICT')

    def test_no_schema_empty_object_multiple_media_and_response_ref(self):
        self.doc['components']['responses'] = {'Shared': {'description': 'ok', 'content': {
            'application/json': {'schema': obj(value={'type': 'string'})},
            'application/problem+json': {'schema': obj(value={'type': 'integer'})},
        }}}
        self.doc['paths']['/a']['post']['responses'] = {
            '200': {'$ref': '#/components/responses/Shared'},
            '204': {'description': 'no content'}, '205': media(obj())}
        self.seed()
        self.run_extract()
        definitions = self.store.get_response_definitions('doc', 'a')
        self.assertEqual(len(definitions), 4)
        no_schema = next(d for d in definitions if d['response_key'] == '204')
        self.assertEqual((no_schema['content_type'], no_schema['extraction_status']), ('', 'NO_SCHEMA'))
        self.assertEqual(len(self.all_fields()), 2)

    def test_unknown_type_needs_source_fix_before_confirmation(self):
        self.doc['paths']['/a']['post']['responses'] = {'200': media(obj(untyped={}))}
        self.seed()
        self.run_extract()
        field = self.field('$.untyped')
        self.assertTrue(field['enabled'])
        self.assertTrue(field['review_required'])
        with self.assertRaises(ValueError):
            self.store.configure_response_output(self.key(field), True, confirm_review=True)

    def test_changed_classification_forces_disabled(self):
        self.run_extract()
        # 200_fail had no established HTTP status without the explicit provider description;
        # a changed classifier simulates a success definition reclassified as a failure.
        classify = impl.response_classify
        with patch.object(impl, 'response_classify', side_effect=lambda key, desc:
                          ('200','FAILURE') if key == '200' else classify(key, desc)):
            self.run_extract()
        self.assertFalse(self.field()['enabled'])

    def test_export_roundtrip_contains_settings_failures_and_source(self):
        self.run_extract()
        files = self.store.export_response_outputs('doc', ['a'])
        payload = json.loads(Path(files[0]).read_text(encoding='utf-8'))
        self.assertEqual(len(payload['outputs']), 4)
        self.assertTrue(any(o['response_kind'] == 'FAILURE' for o in payload['outputs']))
        self.assertEqual(payload['responses'][0]['source_hash'], impl.response_source_hash(self.doc))
        self.assertEqual(payload['query'], {'include_inactive': True, 'include_failures': True})
        self.assertTrue(Path(files[0]).is_relative_to(self.root / 'output' / 'response_outputs'))

    def test_xpath_repeated_rows_and_attributes(self):
        schema = obj(data1={'type':'object', 'xml': {'name':'Dataset'}, 'properties':{
            'id': {'type':'string', 'example':'dsItem', 'xml':{'attribute':True}},
            'data2': {'type':'object', 'xml':{'name':'rows'}, 'properties':{
                'data3': {'type':'object', 'xml':{'name':'row'}, 'properties':{
                    'slitmCd': {'type':'string', 'example':'상품코드(예:001)'}}}}}}})
        schema['xml'] = {'name':'Response2XML'}
        self.doc['paths']['/a']['post']['responses'] = {'200': media(schema, 'application/xml')}
        self.seed()
        self.run_extract()
        field = self.field('$.data1.data2.data3.slitmCd')
        self.assertEqual(field['response_path'], '/Response2XML/Dataset[@id="dsItem"]/rows/row/slitmCd')
        root = ET.fromstring('<Response2XML><Dataset id="dsItem"><rows><row><slitmCd>001</slitmCd></row>'
                             '<row><slitmCd>002</slitmCd></row></rows></Dataset></Response2XML>')
        self.assertEqual([n.text for n in root.findall('.' + field['response_path'][len('/Response2XML'):])], ['001','002'])
        self.assertEqual(field['metadata']['cardinality'], 'UNKNOWN')
        self.assertTrue(self.field('$.data1.id')['response_path'].endswith('/@id'))

    def test_namespaced_wrapped_xml_array(self):
        schema = obj(items={'type':'array', 'xml':{'name':'entries','wrapped':True},
                            'items': {'type':'object', 'xml':{'name':'entry','namespace':'urn:test','prefix':'t'},
                                      'properties':{'id':{'type':'string'}}}})
        schema['xml'] = {'name':'root'}
        self.doc['paths']['/a']['post']['responses'] = {'200':media(schema,'application/xml')}
        self.seed()
        self.run_extract()
        field = self.field('$.items[*].id')
        self.assertEqual(field['response_path'], '/root/entries/t:entry/id')
        root = ET.fromstring('<root xmlns:t="urn:test"><entries><t:entry><id>1</id></t:entry></entries></root>')
        self.assertEqual(root.find('./entries/t:entry/id', field['metadata']['namespaces']).text, '1')
        self.assertEqual(field['metadata']['cardinality'], 'MANY')

    def test_notebook_stage4_execution_cells_are_independent(self):
        notebook = json.loads((PROJECT / 'preprocessing.ipynb').read_text(encoding='utf-8'))
        env = {'PROJECT_DIR': self.root, 'DOCUMENT_ID': 'doc', 'display': lambda *args: None}
        for cell in notebook['cells']:
            if cell['cell_type'] == 'code' and cell.get('id', '').startswith('response-outputs-'):
                exec(compile(''.join(cell['source']), '<stage4 notebook>', 'exec'), env)
        self.assertEqual(env['response_outputs_report']['api_count'], 2)
        self.assertEqual(env['response_outputs_report']['failed_api_count'], 0)
        self.assertFalse(env['RUN_RESPONSE_OUTPUT_CONFIGURATION'])
        self.assertFalse(env['RUN_RESPONSE_OUTPUT_EXPORT'])

    def test_report_saved_and_counts_only_selected_scope(self):
        report = self.run_extract(['b'])
        saved = json.loads(self.store.report_path.read_text(encoding='utf-8'))
        self.assertEqual(saved, report)
        self.assertEqual((report['api_count'], report['output_count'], report['created']), (1,1,1))
        self.assertEqual(self.all_fields(), [])


class SavedSwaggerTests(unittest.TestCase):
    def test_actual_snapshot_43_apis_84_responses(self):
        with tempfile.TemporaryDirectory() as temp:
            store = impl.ResponseOutputs(Path(temp), canonical_db_path=PROJECT / 'output' / 'canonical_schema.db',
                                         raw_path=PROJECT / 'output' / 'swagger_raw.json')
            report = store.initialize_response_outputs('hmall-openapi-v1')
            self.assertEqual(report['failed_api_count'], 0, report['api_results'])
            self.assertEqual((report['api_count'], report['response_count']), (43,84))
            definitions = store.get_response_definitions('hmall-openapi-v1')
            self.assertEqual(sum(d['response_key'] == '200_fail' for d in definitions), 41)
            self.assertTrue(all(d['content_type'] == 'application/xml' for d in definitions))
            fields = store.get_response_outputs('hmall-openapi-v1','multiItem')
            product = next(f for f in fields if f['schema_path'] == '$.data1.data2.data3.slitmCd')
            self.assertEqual(product['response_path'], '/Response2XML/Dataset[@id="dsItem"]/rows/row/slitmCd')
            self.assertTrue(product['enabled'])
            failures = store.get_response_outputs('hmall-openapi-v1', 'selectItem',
                                                  response_key='200_fail', include_inactive=True, include_failures=True)
            self.assertTrue(failures)
            self.assertTrue(all(not f['enabled'] and f['status_code'] == '200' for f in failures))
            self.assertIn('/error/code', [f['response_path'] for f in failures])


if __name__ == '__main__':
    unittest.main(verbosity=2)

