"""JSON 연결 계약: API ID/전체 경로, 승인 필터, 사용자 등록 보존."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from http.server import ThreadingHTTPServer
from threading import Thread
import unittest
from urllib.request import Request, urlopen

from tap.ui.preprocessing import load_preprocessing, save_preprocessing_baseline
from tap.ui.serve import make_handler


class PreprocessingJsonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'demo'
        self.output = self.root / 'data/out/parameters'
        self.api = 'POST:/orders/query.do'
        self.sid = 'hshop-openapi:' + self.api
        self.path = '$.body.data1.venCd'
        self.canonical = {'documentId': 'hshop-openapi', 'apiId': self.api, 'parameters': [
            {'path': self.path, 'xmlPath': '/Root/Dataset/row/venCd', 'name': 'venCd', 'location': 'body',
             'type': 'string', 'required': True, 'requiredDeclared': True,
             'example': '협력사코드(타입:string, 예:001442)'},
            {'path': '$.body.data2.venCd', 'xmlPath': '/Root/Other/venCd', 'name': 'venCd',
             'location': 'body', 'type': 'string', 'required': False, 'example': 'other'},
        ]}
        self.write('canonical_schema/hshop-openapi/a.json', self.canonical)

    def write(self, name, data):
        path = self.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8')

    def test_full_paths_and_api_identity_preserve_duplicate_names_and_leading_zero(self):
        data = load_preprocessing(self.root)
        fields = data['canonical_schema'][self.sid]['parameters']
        self.assertEqual(len(fields), 2)
        self.assertEqual(fields[0]['parameter_path'], self.path)
        self.assertEqual(fields[0]['xmlPath'], '/Root/Dataset/row/venCd')
        record = data['baselines'][self.sid]
        self.assertFalse(record['user_registered'])
        self.assertEqual(record['parameters'][0]['value'], '001442')

    def test_only_canonical_base_and_verified_knowledge_are_exposed(self):
        identity = {'document_id': 'hshop-openapi', 'api_id': self.api, 'parameter_path': self.path}
        base = {'identity': identity, 'provenance': {'source': 'CANONICAL_DERIVED'}}
        verified = {'knowledge_id': 'new', 'status': 'VERIFIED', 'supersedes_id': 'old',
                    'kb_scope': 'API', 'canonical_document_id': 'hshop-openapi', 'api_ids': [self.api]}
        self.write('parameter_kb/api/hshop-openapi/a.json', {
            'document_id': 'hshop-openapi', 'api_id': self.api,
            'parameters': [base, {**base, 'provenance': {'source': 'UNVERIFIED'}}],
            'api_knowledge': [verified, {**verified, 'knowledge_id': 'old', 'supersedes_id': None},
                              {**verified, 'knowledge_id': 'candidate', 'status': 'CANDIDATE'}],
            'common_candidates': []})
        kb = load_preprocessing(self.root)['parameter_kb'][self.sid]
        self.assertEqual(len(kb['parameters']), 1)
        self.assertEqual([k['knowledge_id'] for k in kb['api_knowledge']], ['new'])

    def test_response_filter_joins_exact_response_and_media_type(self):
        identity = {'document_id': 'hshop-openapi', 'api_id': self.api}
        definition = {**identity, 'response_key': '200', 'content_type': 'application/xml',
                      'response_kind': 'SUCCESS', 'is_active': True, 'extraction_status': 'COMPLETE'}
        output = {**definition, 'schema_path': '$.ordNo', 'response_path': '/Result/ordNo', 'path_type': 'XPATH',
                  'enabled': True, 'review_required': False, 'response_is_active': True, 'metadata': {}}
        variants = [output, {**output, 'enabled': False}, {**output, 'review_required': True},
                    {**output, 'response_kind': 'FAILURE'}, {**output, 'content_type': 'application/json'},
                    {**output, 'is_active': False}]
        self.write('response_outputs/hshop-openapi/a.json', {**identity, 'responses': [definition], 'outputs': variants})
        response = load_preprocessing(self.root)['response_outputs'][self.sid]
        self.assertEqual(len(response['outputs']), 1)
        self.assertEqual(response['outputs'][0]['xmlPath'], '/Result/ordNo')
        self.assertEqual(response['on_unmatched_response'], 'stop')

    def test_registered_values_survive_source_regeneration(self):
        destination = save_preprocessing_baseline(self.root, self.sid, {self.path: '000002'})
        self.assertTrue(destination.is_file())
        updated = deepcopy(self.canonical)
        updated['parameters'][0]['example'] = '새예시(예:999999)'
        self.write('canonical_schema/hshop-openapi/a.json', updated)
        baseline = load_preprocessing(self.root)['baselines'][self.sid]
        self.assertTrue(baseline['user_registered'])
        self.assertEqual(baseline['parameters'][0]['value'], '000002')
        self.assertEqual(baseline['example_values'][self.path], '999999')
        with self.assertRaisesRegex(ValueError, '타입'):
            save_preprocessing_baseline(self.root, self.sid, {self.path: 1442})
        with self.assertRaisesRegex(ValueError, 'parameter_path'):
            save_preprocessing_baseline(self.root, self.sid, {'venCd': '001442'})

    def test_refresh_and_registration_endpoints_use_json_and_update_static_snapshot(self):
        (self.root / 'prototype').mkdir(parents=True)
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.root))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def post(path, body):
                request = Request(f'http://127.0.0.1:{server.server_port}{path}',
                                  data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
                with urlopen(request) as response:
                    return json.load(response)
            refreshed = post('/api/preprocessing/refresh', {})
            self.assertIn(self.sid, refreshed['data']['preprocessing']['canonical_schema'])
            snapshot = self.root / 'prototype/tap-data.js'
            self.assertTrue(snapshot.is_file())
            registered = post('/api/preprocessing/baseline', {
                'selected_api_id': self.sid, 'values': {self.path: '000009'}})
            self.assertTrue((self.root / registered['file']).is_file())
            self.assertTrue(registered['data']['preprocessing']['baselines'][self.sid]['user_registered'])
            post('/api/preprocessing/refresh', {})
            saved = json.loads(snapshot.read_text().split('window.TAP_DATA = ', 1)[1].strip().removesuffix(';'))
            self.assertEqual(saved['preprocessing']['baselines'][self.sid]['parameters'][0]['value'], '000009')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
