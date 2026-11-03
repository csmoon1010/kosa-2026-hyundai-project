"""API-scoped retrieval from the demo's existing Chroma vectors; never sync on read."""
from copy import deepcopy
from pathlib import Path
import json
import re
import time

from tap.retrieval.chroma_index import CanonicalChromaIndex, build_parameter_search_text, digest

MODEL = 'text-embedding-3-small'
COLLECTION = 'canonical_parameters_cf5a1c85ad4d'
DIMENSIONS = 1536
DEFAULT_TOP_K = 5


def validate_top_k(value):
    if type(value) is not int or not 1 <= value <= 10:
        raise ValueError('KB top-k는 1~10의 정수여야 합니다')
    return value


def condition_queries(conditions):
    """Reuse structured intent; no model-based query decomposition."""
    if isinstance(conditions, str):
        return [conditions.strip()] if conditions.strip() else []
    if isinstance(conditions, list):
        return list(dict.fromkeys(q for item in conditions for q in condition_queries(item)))
    if isinstance(conditions, dict):
        for key in ('search_query', 'term', 'meaning', 'description', 'field'):
            if isinstance(conditions.get(key), str) and conditions[key].strip():
                parts = [conditions[key].strip()]
                terms = conditions.get('terms') or []
                if isinstance(terms, str): terms = [terms]
                if isinstance(terms, list): parts.extend(t for t in terms if isinstance(t, str))
                if isinstance(conditions.get('context'), str):
                    parts.append(conditions['context'])
                return ['\n'.join(parts)]
        # Support a nested structured conditions envelope, without treating a
        # bare numeric value as a meaningful semantic query.
        return list(dict.fromkeys(q for key, value in conditions.items()
                                  if key not in ('value', 'unit', 'source_pointer', 'condition_id')
                                  for q in condition_queries(value)))
    return []


class ExistingChromaIndex(CanonicalChromaIndex):
    def _open(self):
        if self._collection is None:
            if not (self.directory / 'chroma.sqlite3').is_file():
                raise FileNotFoundError('데모 ChromaDB가 없습니다: ' + str(self.directory))
            import chromadb
            from chromadb.config import Settings
            self._client = chromadb.PersistentClient(path=str(self.directory),
                settings=Settings(anonymized_telemetry=False))
            self._collection = self._client.get_collection(COLLECTION, embedding_function=None)
            metadata = self._collection.metadata or {}
            if metadata.get('model_name') != MODEL or metadata.get('dimensions') not in ('model_default', DIMENSIONS):
                raise ValueError('기존 Chroma 컬렉션의 임베딩 모델·차원이 일치하지 않습니다')
        return self._collection


class KBRetriever:
    def __init__(self, root, top_k=DEFAULT_TOP_K, index=None, max_distance=0.85):
        self.top_k = validate_top_k(top_k)
        if not isinstance(max_distance, (int, float)) or not 0 <= max_distance <= 2:
            raise ValueError('cosine 거리 임계값은 0~2여야 합니다')
        self.max_distance = max_distance
        self.index = index or ExistingChromaIndex(
            Path(root).resolve() / 'data/out/parameters/parameter_vectors', model_name=MODEL)

    def select(self, full, canonical, conditions, scope='search', paths=None, budget=None,
               original_question=None, selection_reason=None, related_steps=None, related_step_threshold=None):
        started = time.monotonic()
        fields = full['data']['parameters']
        all_paths = {f['identity']['parameter_path'] for f in fields}
        paths = paths or []
        if scope == 'paths' and not paths:
            raise ValueError('paths 조회에는 parameter_paths가 필요합니다')
        if set(paths) - all_paths:
            raise ValueError('현재 API KB에 없는 parameter_path입니다')
        k = 10 if scope == 'expand' else self.top_k
        related_steps = related_steps or []
        related_groups = {}
        for step in related_steps:
            step_conditions = condition_queries(step.get('conditions'))
            if step_conditions:
                key = (step.get('task_sequence'), step.get('action'), tuple(step_conditions))
                related_groups.setdefault(key, []).append(step.get('step_id'))
        related_lines = []
        for (sequence, action, step_conditions), step_ids in related_groups.items():
            label = ','.join(str(step_id) for step_id in step_ids if step_id)
            if sequence is not None:
                label = f'업무 {sequence} STEP {label}'
            if action:
                label += f' ({action})'
            related_lines.append(f'관련 {label}: ' + ' / '.join(step_conditions))
        base_conditions = condition_queries(conditions)
        if not base_conditions and related_lines:
            base_conditions = ['']
        condition_context = '\n'.join(related_lines)
        query_rows = [{'source': 'condition', 'query':
                       (f'현재 STEP 조건: {q}\n' if q and condition_context else q) + condition_context
                       if condition_context else q} for q in base_conditions]
        for source, value in (('original_question', original_question), ('selection_reason', selection_reason)):
            if isinstance(value, str) and value.strip():
                query_rows.append({'source': source, 'query': value.strip()})
        # Deduplicate identical texts while retaining every source label.
        unique = {}
        for row in query_rows:
            entry = unique.setdefault(row['query'], {'query': row['query'], 'sources': []})
            if row['source'] not in entry['sources']:
                entry['sources'].append(row['source'])
        query_rows = list(unique.values())
        queries = [row['query'] for row in query_rows]
        report = dict(scope=scope, top_k=k, queries=query_rows, model=MODEL, collection=COLLECTION,
                      index_path=str(self.index.directory), max_distance=self.max_distance, embedding_tokens=0, embedding_calls=0,
                      embedding_seconds=0, fallback_reason=None, total_fields=len(fields),
                      related_steps=[{key: step.get(key) for key in
                                      ('step_id','edge','action','score','basis','reason','conditions')}
                                     for step in related_steps],
                      related_step_threshold=related_step_threshold)
        selected = set(paths)
        if scope == 'full' or not queries:
            selected = all_paths
            report['fallback_reason'] = 'explicit_full' if scope == 'full' else 'empty_conditions'
        elif scope != 'paths':
            try:
                collection = self.index._open()
                document_id, api_id = canonical['documentId'], canonical['apiId']
                where = {'$and': [{'document_id': document_id}, {'api_id': api_id}, {'active': True}]}
                stored = collection.get(where=where, include=['metadatas', 'documents'])
                by_path = {}
                definitions = {p['path']: p for p in canonical['parameters']}
                for meta, text in zip(stored['metadatas'], stored['documents']):
                    path = meta.get('parameter_path')
                    if path not in all_paths:
                        continue
                    # The original index hashes [search text, Canonical field].
                    # Check current technical definition and generated search text.
                    expected = build_parameter_search_text(canonical, definitions[path], [])
                    if text != expected or meta.get('content_hash') != digest([text, definitions[path]]):
                        raise ValueError('stale_index: ' + path)
                    by_path[path] = meta
                if set(by_path) != all_paths:
                    raise ValueError('incomplete_api_index')
                remaining, seconds = budget() if budget else (None, 60)
                if remaining is not None and len(json.dumps(queries, ensure_ascii=False).encode('utf-8')) + 128 >= remaining:
                    raise ValueError('embedding_token_budget')
                from openai import OpenAI
                if self.index._embedding_client is None:
                    self.index._embedding_client = OpenAI(max_retries=0)
                encoded_at = time.monotonic()
                report['embedding_calls'] = 1
                response = self.index._embedding_client.embeddings.create(
                    model=MODEL, input=queries, encoding_format='float', timeout=min(seconds, 60))
                report['embedding_tokens'] = response.usage.total_tokens
                report['embedding_seconds'] = round(time.monotonic() - encoded_at, 4)
                if remaining is not None and response.usage.total_tokens >= remaining:
                    # Let runtime account the received usage and enforce the budget.
                    raise ValueError('embedding_token_budget')
                vectors = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
                if len(vectors) != len(queries) or any(len(v) != DIMENSIONS for v in vectors):
                    raise ValueError('임베딩 응답의 차원·개수가 일치하지 않습니다')
                ranked = collection.query(query_embeddings=vectors, where=where,
                    n_results=min(k, len(by_path)), include=['metadatas', 'distances'])
                if k < 10 and any(not values or values[0] > self.max_distance for values in ranked['distances']):
                    report['expanded_from'] = k
                    k = 10
                    report['top_k'] = k
                    ranked = collection.query(query_embeddings=vectors, where=where,
                        n_results=min(k, len(by_path)), include=['metadatas', 'distances'])
                report['rankings'] = []
                for query, metas, distances in zip(queries, ranked['metadatas'], ranked['distances']):
                    rows = [dict(parameter_path=m['parameter_path'], distance=d)
                            for m, d in zip(metas, distances) if m['parameter_path'] in all_paths]
                    if not rows:
                        raise ValueError('empty_condition_results')
                    if rows[0]['distance'] > self.max_distance:
                        raise ValueError('low_similarity: ' + query)
                    query_info = query_rows[len(report['rankings'])]
                    report['rankings'].append(dict(query=query, sources=query_info['sources'], candidates=rows))
                    selected.update(r['parameter_path'] for r in rows)
                # Exact names/aliases are an additive safety net, not a substitute
                # for semantic search. Keep all rules with linked fields below.
                for field in fields:
                    knowledge = field.get('knowledge') or {}
                    terms = [field['identity'].get('parameter_name'), knowledge.get('description'),
                             knowledge.get('display_name')]
                    terms += [a if isinstance(a, str) else a.get('value') for a in knowledge.get('aliases', [])]
                    if any(term and any(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', q) for q in queries)
                           for term in terms if isinstance(term, str)):
                        selected.add(field['identity']['parameter_path'])
            except Exception as error:
                if report['embedding_calls']:
                    report['embedding_seconds'] = round(time.monotonic() - encoded_at, 4)
                selected = all_paths
                report['fallback_reason'] = str(error)
        # Preserve fields explicitly linked by knowledge records; source pointers
        # remain original offsets even after this list is filtered.
        changed = True
        while changed:
            before = len(selected)
            for field in fields:
                if field['identity']['parameter_path'] not in selected:
                    continue
                text = json.dumps(field.get('knowledge') or {}, ensure_ascii=False)
                selected.update(path for path in all_paths if path in text)
            changed = len(selected) != before
        result = deepcopy(full)
        result['data']['parameters'] = [f for f in fields if f['identity']['parameter_path'] in selected]
        report.update(selected_fields=len(result['data']['parameters']),
                      elapsed_seconds=round(time.monotonic()-started, 4))
        result['retrieval'] = report
        return result
