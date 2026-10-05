"""그래프 스트리밍·대화 상태·최초 적재의 핵심 동작 확인. 외부 API 사용 없음."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tiktoken
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from streamlit.testing.v1 import AppTest

from adaptive_rag import AdaptiveRoute, ResolvedQuestion, build_adaptive_graph
from chat_service import resolve_question, stream_reply
from prepare_index import ensure_indexes
from rag_config import load_settings
from run_history import RunRecorder, CountedQueryEmbeddings, CURRENT_RUN, token_cost, search_route_reason
from source_downloads import prepare_downloads, render_source_downloads


class LocalEmbeddings(Embeddings):
    # 외부 API 없이 문서용 테스트 임베딩을 반환한다.
    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    # 외부 API 없이 질문용 테스트 임베딩을 반환한다.
    def embed_query(self, text):
        return [1.0, 0.0, 0.0]


class ChatbotTests(unittest.TestCase):
    # 각 테스트에서 사용할 공통 설정과 문서를 준비한다.
    def setUp(self):
        self.settings = load_settings()
        self.doc = Document(page_content='사진 제출 가능', metadata={'source': 'sample.pdf', 'page': 3})

    # 모의 모델과 검색기로 테스트용 그래프 자원을 구성한다.
    def resources(self, kind='기본', confidence=.99, broken=False):
        self.calls = []

        # 지정한 검색 경로의 동작을 모사하는 함수를 만든다.
        def search(name):
            # 검색 호출을 기록하고 테스트 문서 또는 오류를 반환한다.
            def run(question):
                self.calls.append((name, question))
                if broken and name != 'base_search':
                    raise ValueError('special failed')
                return [self.doc]
            return RunnableLambda(run)

        resources = {'classifier': RunnableLambda(lambda _: AdaptiveRoute(
            route_type=kind, confidence=confidence, reason='유형별 검색')),
            'retrievers': {name: search(name) for name in (
                'base_search', 'parent_document_search', 'llm_rerank_search')},
            'resolver': RunnableLambda(lambda _: ResolvedQuestion(
                resolved_question='사진 제출 가능 여부', needs_clarification=False, clarification_question='')),
            'answer_chain': RunnableLambda(lambda _: '질문') |
                FakeListChatModel(responses=['사진을 제출할 수 있습니다. [1]']) | StrOutputParser()}
        resources['graph'] = build_adaptive_graph(resources, self.settings)
        return resources

    # 검색 분기와 기본 검색 복귀 및 그래프 토큰 전달을 확인한다.
    def test_routes_fallback_and_real_graph_token_events(self):
        for kind, confidence, broken, expected in [
            ('기본', .99, False, 'base_search'),
            ('조건', .99, False, 'parent_document_search'),
            ('부정/예외', .99, False, 'llm_rerank_search'),
            ('조건', .5, False, 'base_search'),
            ('조건', .99, True, 'base_search'),
            ('부정/예외', .99, True, 'base_search'),
        ]:
            with self.subTest(kind=kind, confidence=confidence, broken=broken):
                resources = self.resources(kind, confidence, broken)
                result = {}
                resolution = {'resolved_question': '자료 질문', 'needs_clarification': False, 'history': ''}
                chunks = list(stream_reply('원질문', resolution, resources, result))
                self.assertGreater(len(chunks), 1)
                self.assertEqual(''.join(chunks), result['content'])
                self.assertEqual(result['trace']['selected_route'], expected)
                self.assertEqual(result['sources'], [{'context_number': 1, 'source': 'sample.pdf', 'page': 3}])
                self.assertTrue(all(question == '자료 질문' for _, question in self.calls))
                self.assertEqual(result['status'], 'complete')
                self.assertNotIn('[1]', result['content'])
                self.assertIn('**&lt;출처&gt;**', result['content'])
                self.assertIn('sample.pdf — 3페이지', result['content'])
                self.assertFalse(any('[' in chunk for chunk in chunks))

    def test_references_only_include_cited_pages_and_deduplicate(self):
        resources = self.resources()
        docs = [self.doc, self.doc, Document(page_content='다른 근거',
                metadata={'source': 'other.pdf', 'page': 7})]
        resources['retrievers']['base_search'] = RunnableLambda(lambda _: docs)
        resources['answer_chain'] = RunnableLambda(lambda _: '질문') | FakeListChatModel(
            responses=['사진 제출이 가능합니다. [1][2]']) | StrOutputParser()
        resources['graph'] = build_adaptive_graph(resources, self.settings)
        result = {}
        chunks = list(stream_reply('질문', {'resolved_question': '질문',
            'needs_clarification': False, 'history': ''}, resources, result))
        self.assertEqual(''.join(chunks), result['content'])
        self.assertEqual(result['content'].count('sample.pdf — 3페이지'), 1)
        self.assertNotIn('other.pdf', result['content'])

    def test_answer_without_evidence_has_no_references(self):
        resources = self.resources()
        resources['answer_chain'] = RunnableLambda(lambda _: '질문') | FakeListChatModel(
            responses=['제공된 문서에서 정보를 찾을 수 없습니다.']) | StrOutputParser()
        resources['graph'] = build_adaptive_graph(resources, self.settings)
        result = {}
        list(stream_reply('질문', {'resolved_question': '질문',
            'needs_clarification': False, 'history': ''}, resources, result))
        self.assertEqual(result['sources'], [])
        self.assertNotIn('출처', result['content'])

    # 질문 분류가 실패하면 기본 검색으로 복귀하는지 확인한다.
    def test_classifier_failure_falls_back(self):
        resources = self.resources()
        # 분류 실패 시 기본 검색 복귀를 확인하기 위한 오류를 발생시킨다.
        def fail(_):
            raise ValueError('classification failed')
        resources['classifier'] = RunnableLambda(fail)
        resources['graph'] = build_adaptive_graph(resources, self.settings)
        result = {}
        list(stream_reply('질문', {'resolved_question': '질문', 'needs_clarification': False,
                                  'history': ''}, resources, result))
        self.assertTrue(result['trace']['fallback'])
        self.assertEqual(result['trace']['selected_route'], 'base_search')

    # 대화 이력 제한과 오류 응답 제외가 적용되는지 확인한다.
    def test_history_limits_and_error_exclusion(self):
        captured = []
        resolver = RunnableLambda(lambda payload: captured.append(payload) or ResolvedQuestion(
            resolved_question='NFC 주스 사진 제출 가능 여부', needs_clarification=False, clarification_question=''))
        messages = []
        for i in range(8):
            messages.extend([{'role': 'user', 'content': f'질문{i}'},
                             {'role': 'assistant', 'content': f'답변{i}', 'status': 'complete'}])
        messages.extend([{'role': 'user', 'content': '실패 질문'},
                         {'role': 'assistant', 'content': '오류 안내', 'status': 'error'}])
        original = copy.deepcopy(messages)
        resolution = resolve_question('그 자료는?', messages, resolver, self.settings)
        history = json.loads(resolution['history'])
        self.assertEqual(len(history), 12)
        self.assertEqual(history[0]['content'], '질문2')
        self.assertEqual(messages, original)
        self.assertNotIn('오류 안내', resolution['history'])
        self.assertEqual(captured[0]['question'], '그 자료는?')
        oversized = [{'role': 'user', 'content': 'NFC 주스 자료'},
                     {'role': 'assistant', 'content': '긴 답변 ' * 7000, 'status': 'complete'}]
        resolution = resolve_question('사진도 가능?', oversized, resolver, self.settings)
        count = len(tiktoken.get_encoding('o200k_base').encode(resolution['history']))
        self.assertLessEqual(count, 4000)
        self.assertIn('NFC 주스 자료', resolution['history'])

    # 확인 질문은 검색 없이 반환하고 다음 대화 이력에 남기는지 확인한다.
    def test_clarification_does_not_search_and_is_retained(self):
        resources = self.resources()
        result = {}
        resolution = {'resolved_question': '', 'needs_clarification': True,
                      'clarification_question': '어떤 신청인가요?', 'history': ''}
        self.assertEqual(list(stream_reply('언제까지?', resolution, resources, result)), ['어떤 신청인가요?'])
        self.assertEqual(self.calls, [])
        followup = resolve_question('쇼핑라이브 편성이요', [
            {'role': 'user', 'content': '언제까지?'}, {'role': 'assistant', **result}],
            resources['resolver'], self.settings)
        self.assertIn('어떤 신청인가요?', followup['history'])

    # 중단된 스트림을 완료 답변으로 저장하지 않는지 확인한다.
    def test_interrupted_stream_is_not_complete(self):
        class BrokenGraph:
            # 스트리밍 도중 연결이 끊기는 상황을 모사한다.
            def stream(self, state, stream_mode):
                yield 'updates', {'base_search': {'docs': [Document(page_content='근거')]}}
                raise RuntimeError('connection interrupted')
        result = {}
        with self.assertRaises(RuntimeError):
            list(stream_reply('질문', {'resolved_question': '질문', 'needs_clarification': False,
                                      'history': ''}, {'graph': BrokenGraph()}, result))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['sources'], [])

    # 최초 구축과 인덱스 재사용 및 운영 중 변경 감지를 확인한다.
    def test_first_build_reuse_and_runtime_change(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = {**self.settings, 'embedding_model': 'local-test-embedding',
                        'chroma_path': str(Path(folder) / 'db'),
                        'parent_path': str(Path(folder) / 'parents')}
            with patch('prepare_index.load_and_split_documents', return_value=([self.doc], [self.doc])) as parse, \
                 patch('prepare_index.OpenAIEmbeddings', return_value=LocalEmbeddings()):
                ensure_indexes(settings)
                ensure_indexes(settings)
                self.assertEqual(parse.call_count, 1)
                import chromadb
                client = chromadb.PersistentClient(path=settings['chroma_path'])
                self.assertEqual(client.get_collection(settings['base_collection']).count(), 1)
                self.assertEqual(client.get_collection(settings['child_collection']).count(), 1)
                parent_file = next(Path(settings['parent_path']).rglob('*'))
                parent_file.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, '운영 중'):
                    ensure_indexes(settings)

    # 불완전한 저장소를 자동 구축하지 않는지 확인한다.
    def test_incomplete_storage_does_not_build(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = {**self.settings, 'embedding_model': 'local-test-embedding',
                        'chroma_path': str(Path(folder) / 'db'),
                        'parent_path': str(Path(folder) / 'parents')}
            Path(settings['parent_path']).mkdir()
            (Path(settings['parent_path']) / 'orphan').write_text('orphan')
            with patch('prepare_index.load_and_split_documents') as parse:
                with self.assertRaisesRegex(ValueError, '불완전'):
                    ensure_indexes(settings)
                parse.assert_not_called()

    # 기존 BASE를 보존하면서 누락된 부모와 자식만 준비하는지 확인한다.
    def test_existing_base_missing_parents_builds_only_missing(self):
        import chromadb
        with tempfile.TemporaryDirectory() as folder:
            settings = {**self.settings, 'embedding_model': 'local-test-embedding',
                        'chroma_path': str(Path(folder) / 'db'),
                        'parent_path': str(Path(folder) / 'parents')}
            client = chromadb.PersistentClient(path=settings['chroma_path'])
            base = client.create_collection(settings['base_collection'], metadata={
                'embedding_model': 'local-test-embedding'})
            base.add(ids=['existing'], documents=['기존 BASE 원문'], embeddings=[[1., 0., 0.]])
            with patch('prepare_index.load_and_split_documents', return_value=([self.doc], [self.doc])), \
                 patch('prepare_index.OpenAIEmbeddings', return_value=LocalEmbeddings()):
                ensure_indexes(settings)
                self.assertEqual(base.get()['ids'], ['existing'])
                self.assertEqual(base.get()['documents'], ['기존 BASE 원문'])
                self.assertEqual(client.get_collection(settings['child_collection']).count(), 1)

    # 호환되지 않는 BASE는 PDF 파싱 전에 거부하는지 확인한다.
    def test_incompatible_base_rejected_before_parsing(self):
        import chromadb
        with tempfile.TemporaryDirectory() as folder:
            settings = {**self.settings, 'chroma_path': str(Path(folder) / 'db'),
                        'parent_path': str(Path(folder) / 'parents')}
            client = chromadb.PersistentClient(path=settings['chroma_path'])
            base = client.create_collection(settings['base_collection'], metadata={
                'embedding_model': 'different-model'})
            base.add(ids=['existing'], documents=['기존 원문'], embeddings=[[1., 0., 0.]])
            with patch('prepare_index.load_and_split_documents') as parse:
                with self.assertRaisesRegex(ValueError, '임베딩 설정'):
                    ensure_indexes(settings)
                parse.assert_not_called()
                self.assertEqual(base.get()['ids'], ['existing'])

    # 채팅 UI와 자원 재사용 및 세션 분리와 초기화를 확인한다.
    def test_streamlit_ui_cache_sessions_and_reset(self):
        resources = self.resources()
        script = Path(__file__).resolve().parents[1] / 'streamlit_chat.py'
        with patch('adaptive_rag.prepare_resources', return_value=resources) as prepare, \
             patch('prepare_index.ensure_indexes'):
            first = AppTest.from_file(str(script), default_timeout=20).run()
            self.assertEqual(len(first.exception), 0)
            first.chat_input[0].set_value('자료?').run()
            self.assertEqual(len(first.exception), 0)
            self.assertEqual(len(first.chat_message), 2)
            self.assertEqual(first.session_state['messages'][1]['status'], 'complete')
            self.assertTrue(first.session_state['messages'][1]['sources'])
            second = AppTest.from_file(str(script), default_timeout=20).run()
            self.assertEqual(second.session_state['messages'], [])
            self.assertEqual(prepare.call_count, 1)
            self.assertEqual(len(first.expander), 1)
            self.assertEqual(len(first.button), 2)
            self.assertEqual(len(first.metric), 1)
            self.assertEqual(len(first.session_state['run_history']), 1)
            record = first.session_state['run_history'][0]
            self.assertEqual(record['contexts'][0]['본문'], self.doc.page_content)
            self.assertTrue(record['contexts'][0]['답변에 인용'])
            self.assertTrue(record['telemetry']['steps'])
            names = {step['단계'] for step in record['telemetry']['steps']}
            self.assertTrue({'질문 분류', '기본 벡터 검색', '답변 생성'}.issubset(names))
            self.assertTrue(record['telemetry']['api_calls'])
            first.button[0].click().run()
            self.assertEqual(len(first.exception), 0)
            self.assertEqual(first.session_state['screen'], 'history')
            self.assertGreater(len(first.dataframe), 0)
            self.assertEqual(len(first.chat_input), 0)
            self.assertEqual(len(first.selectbox), 0)
            columns = list(first.dataframe[0].value.columns)
            self.assertEqual(columns[-1], '전체(초)')
            self.assertNotIn('답변 생성(초)', columns)
            first.session_state['history_runs_grid'] = {
                'selection': {'rows': [0], 'columns': [], 'cells': []}}
            first.run()
            self.assertEqual(len(first.exception), 0)
            self.assertTrue(any(item.value == '실행 1 상세' for item in first.subheader))
            self.assertTrue(any('시간·API 사용량' in tab.label for tab in first.tabs))
            first.button[0].click().run()
            self.assertEqual(first.session_state['screen'], 'chat')
            first.button[1].click().run()
            self.assertEqual(first.session_state['messages'], [])
            self.assertEqual(len(first.session_state['run_history']), 1)
            self.assertEqual(second.session_state['run_history'], [])
            self.assertEqual(prepare.call_count, 1)

    def test_notebook_cost_snapshot_and_request_isolation(self):
        settings = {**self.settings, 'model': 'gpt-5.4', 'lower_model': 'gpt-5.4-mini',
                    'embedding_model': 'text-embedding-3-small'}
        recorder = RunRecorder(settings)
        recorder.add_usage('분류', 'gpt-5.4-mini-2026-03-17',
            {'input_tokens': 1000, 'output_tokens': 100,
             'input_token_details': {'cache_read': 500}}, .5)
        recorder.add_usage('임베딩', 'text-embedding-3-small', {'input_tokens': 100}, .1)
        snapshot = recorder.snapshot()
        self.assertEqual(snapshot['total_tokens'], 1200)
        self.assertAlmostEqual(snapshot['cost_usd'], .001202)
        recorder.add_usage('답변', 'unknown-model', {'input_tokens': 1}, .1)
        self.assertIsNone(recorder.snapshot()['cost_usd'])
        self.assertEqual(len(snapshot['api_calls']), 2)
        self.assertEqual(RunRecorder(settings).snapshot()['total_tokens'], 0)
        with recorder.bind():
            self.assertIs(CURRENT_RUN.get(), recorder)
        self.assertIsNone(CURRENT_RUN.get())

    def test_error_keeps_measured_steps(self):
        recorder = RunRecorder(self.settings)
        with self.assertRaises(ValueError):
            with recorder.bind(), recorder.measure('질문 보완'):
                raise ValueError('failed')
        self.assertEqual(recorder.snapshot()['steps'][0]['상태'], '오류')
        self.assertIsNone(CURRENT_RUN.get())

    def test_search_route_reason_explains_policy_and_actual_fallback(self):
        reason = search_route_reason({'selected_route': 'parent_document_search',
            'classification_reason': '필수 제출자료를 묻는 질문', 'fallback': False})
        self.assertIn('Parent Document', reason)
        self.assertIn('필수 제출자료', reason)
        reason = search_route_reason({'selected_route': 'base_search', 'route_type': '조건',
            'fallback': True, 'fallback_reason': '분류 확신도 기준 미달'})
        self.assertIn('기본 벡터 검색으로 복귀', reason)
        self.assertIn('분류 확신도 기준 미달', reason)
        self.assertNotIn('기본 질문으로 분류', reason)

    def test_source_downloads_are_lazy_and_deduplicate_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            content = b'%PDF-1.4 test document'
            (root / 'manual.pdf').write_bytes(content)
            sources = [{'source': 'manual.pdf', 'page': 1},
                       {'source': 'manual.pdf', 'page': 2},
                       {'source': 'missing.pdf'}, {'source': '../outside.pdf'},
                       {'source': None}]
            with patch.object(Path, 'read_bytes', return_value=content) as read:
                downloads = prepare_downloads(sources, root)
                self.assertEqual(len(downloads), 1)
                read.assert_not_called()
                with patch('source_downloads.prepare_downloads', return_value=downloads), \
                     patch('streamlit.download_button') as button:
                    render_source_downloads(sources, 'test')
                    read.assert_not_called()
                    self.assertEqual(button.call_args.kwargs['on_click'], 'ignore')
                    reader = button.call_args.kwargs['data']
                    self.assertTrue(callable(reader))
                    self.assertEqual(reader(), content)
                    read.assert_called_once()

    def test_embedding_estimate_uses_notebook_encoder_and_request_recorder(self):
        from unittest.mock import Mock
        delegate = Mock(model=self.settings['embedding_model'])
        delegate.embed_query.return_value = [1., 0.]
        embedding = CountedQueryEmbeddings(delegate)
        recorder = RunRecorder(self.settings)
        other = RunRecorder(self.settings)
        with patch('tiktoken.get_encoding') as encoding:
            encoding.return_value.encode.return_value = [1, 2, 3]
            with recorder.bind():
                self.assertEqual(embedding.embed_query('질문'), [1., 0.])
            encoding.assert_called_once_with('cl100k_base')
            encoding.return_value.encode.assert_called_once_with('질문', disallowed_special=())
        self.assertEqual(recorder.snapshot()['total_tokens'], 3)
        self.assertEqual(other.snapshot()['total_tokens'], 0)

    def test_api_usage_callback_records_actual_tokens_and_snapshot_model(self):
        from uuid import uuid4
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, LLMResult
        settings = {**self.settings, 'lower_model': 'gpt-5.4-mini'}
        recorder = RunRecorder(settings)
        run_id = uuid4()
        recorder.on_chat_model_start({}, [], run_id=run_id,
            metadata={'ls_model_name': 'gpt-5.4-mini', 'langgraph_node': 'generate_answer'})
        message = AIMessage(content='답변', usage_metadata={'input_tokens': 100,
            'output_tokens': 10, 'total_tokens': 110},
            response_metadata={'model_name': 'gpt-5.4-mini-2026-03-17'})
        recorder.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id)
        snapshot = recorder.snapshot()
        self.assertEqual(snapshot['total_tokens'], 110)
        self.assertAlmostEqual(snapshot['cost_usd'], .00012)
        self.assertEqual(snapshot['model_usage']['gpt-5.4-mini-2026-03-17']['total_tokens'], 110)


if __name__ == '__main__':
    unittest.main()
