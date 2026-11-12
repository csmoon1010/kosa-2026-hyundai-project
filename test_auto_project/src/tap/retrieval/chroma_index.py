"""Chroma helpers copied from mini_project_2/preprocessing.ipynb cells 27, 29, 33.

Preserves source serialization, collection signature, search filtering and sync logic.
Not connected to the Scenario IR runtime by this copy operation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(dumps(value).encode('utf-8')).hexdigest()

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class ConceptRef(StrictModel):
    ref_id: str = Field(min_length=1)
    term: str = Field(min_length=1)
    role: Literal['SUBJECT', 'CONDITION', 'TARGET']
    terms: list[str] = Field(default_factory=list)  # 추가검색어
    context: str | None = None


# ConceptRef의 검색어 변환 : 개념별로 원문에서 얻은 용어와 짧은 설명만 사용해 검색어를 구성한다.
# API 임베딩 대상 텍스트 구성 : 승인된 API 의미·별칭을 Canonical 설명에 보완하되 값 예시·enum은 임베딩에서 제외한다.
# 필드명, 설명, 승인된 의미, 별칭, 상위 경로, API 업무와 설명
def build_parameter_search_text(api, parameter, approved_knowledge):
    aliases, meanings = [], []
    for k in approved_knowledge:
        if k['kb_scope'] != 'API' or k['kind'] not in ('ALIAS', 'MEANING'):
            continue
        if not any(t['document_id'] == api['documentId'] and t['api_id'] == api['apiId'] and
                   t['parameter_path'] == parameter['path'] for t in k['targets']):
            continue
        (aliases if k['kind'] == 'ALIAS' else meanings).append(k['payload']['value'])
    parts = [f"필드명: {parameter['name']}", '필드 설명: ' + (parameter.get('description') or '')]
    if meanings:
        parts.append('승인된 의미: ' + '; '.join(sorted(set(meanings))))
    if aliases:
        parts.append('승인된 별칭: ' + ', '.join(sorted(set(aliases))))
    parts.append('상위 경로: ' + parameter['path'].rsplit('.', 1)[0])
    if parameter.get('xmlPath'):
        parts.append('XML 상위 경로: ' + parameter['xmlPath'].rsplit('/', 1)[0])
    parts += ['API 업무: ' + (api.get('summary') or ''),
              'API 설명: ' + (api.get('description') or '')[:300]]
    return '\n'.join(parts)


# Canonical의 Chroma 저장 : 필드별 검색용 벡터를 Chroma에 영속 저장하고 변경된 레코드만 갱신한다.
class CanonicalChromaIndex:
    # 임베딩 초기화 : OpenAI 모델·차원별 컬렉션으로 기존 다른 모델의 벡터와 혼합하지 않는다.
    def __init__(self, directory, model_name=None, dimensions=None, batch_size=32, timeout_seconds=60.0):
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError('batch_size는 1 이상의 정수입니다.')
        if dimensions is not None and (type(dimensions) is not int or dimensions < 1):
            raise ValueError('dimensions는 None 또는 1 이상의 정수입니다.')
        self.directory = Path(directory).resolve()
        self.model_name = (model_name or os.environ.get('OPENAI_EMBEDDING_MODEL', '')).strip()
        if not self.model_name:
            raise ValueError('.env의 OPENAI_EMBEDDING_MODEL을 설정하세요.')
        self.dimensions, self.batch_size = dimensions, batch_size
        self.timeout_seconds = timeout_seconds
        self.signature = digest(['openai', self.model_name, dimensions, 'canonical-field-v2'])
        self.collection_name = 'canonical_parameters_' + self.signature[:12]
        self._client, self._collection, self._embedding_client = None, None, None

    # ChromaDB 열기 : Chroma는 벡터 저장만 맡고 임베딩은 명시적으로 OpenAI API에서 생성한다.
    def _open(self):
        if self._collection is None:
            import chromadb
            self.directory.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.directory))
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name, embedding_function=None,
                metadata={'embedding_provider': 'openai', 'model_name': self.model_name,
                          'dimensions': self.dimensions or 'model_default', 'index_signature': self.signature},
                configuration={'hnsw': {'space': 'cosine'}})
        return self._collection

    # 임베딩 벡터 변환 : 문서·query에 같은 OpenAI 모델을 사용하며 E5 전용 접두어를 붙이지 않는다.
    def _encode(self, texts):
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError('임베딩 입력은 비어 있지 않은 문자열이어야 합니다.')
        if self._embedding_client is None:
            from openai import OpenAI
            self._embedding_client = OpenAI(timeout=self.timeout_seconds)
        kwargs = {'dimensions': self.dimensions} if self.dimensions is not None else {}
        response = self._embedding_client.embeddings.create(
            model=self.model_name, input=texts, encoding_format='float', **kwargs)
        items = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in items] != list(range(len(texts))):
            raise ValueError('임베딩 응답 개수 또는 입력 순서가 일치하지 않습니다.')
        vectors = [item.embedding for item in items]
        if any(not v or len(v) != len(vectors[0]) or any(not math.isfinite(x) for x in v) for v in vectors):
            raise ValueError('임베딩 응답의 차원 또는 숫자 값이 유효하지 않습니다.')
        if self.dimensions is not None and len(vectors[0]) != self.dimensions:
            raise ValueError('요청한 임베딩 차원과 응답 차원이 다릅니다.')
        return vectors

    # 범위 제한 : 문서/API 범위를 먼저 제한하며 전체 동기화 때만 삭제된 API까지 정리한다.
    def _where(self, document_id, api_ids=None):
        filters = [{'document_id': document_id}]
        if api_ids is not None:
            if not api_ids:
                raise ValueError('빈 API 목록은 검색 범위로 사용할 수 없습니다.')
            filters.append({'api_id': {'$in': api_ids}})
        return filters[0] if len(filters) == 1 else {'$and': filters}

    # 크로마db 컬렉션 저장 : 검색 텍스트·승인 별칭·Canonical 정의가 변한 필드를 upsert하고 삭제 필드는 제거한다.
    def sync(self, records, document_id, api_ids=None):
        collection = self._open()
        current = collection.get(where=self._where(document_id, api_ids), include=['metadatas'])
        stored = dict(zip(current['ids'], current['metadatas']))
        wanted = {r['candidate_id']: r for r in records}
        if len(wanted) != len(records):
            raise ValueError('중복된 Canonical 복합키입니다.')
        changed = [r for cid, r in wanted.items() if (stored.get(cid) or {}).get('content_hash') != r['content_hash']]
        for start in range(0, len(changed), self.batch_size):
            batch = changed[start:start + self.batch_size]
            collection.upsert(ids=[r['candidate_id'] for r in batch],
                embeddings=self._encode([r['search_text'] for r in batch]),
                documents=[r['search_text'] for r in batch],
                metadatas=[{**{key: r[key] for key in ('document_id', 'api_id', 'parameter_path')},
                            'location': r['parameter']['location'], 'active': True,
                            'content_hash': r['content_hash'], 'model_name': self.model_name} for r in batch])
        obsolete = sorted(set(stored) - set(wanted))
        if obsolete:
            collection.delete(ids=obsolete)
        return {'collection': self.collection_name, 'parameters': len(records),
                'updated': len(changed), 'removed': len(obsolete)}

    #유사도 검색(top_k) : 지정 API 안에서만 의미 검색하며 거리값을 LLM 확신 점수와 구분한다.
    def search(self, query, document_id, api_id, candidates, top_k):
        if not candidates:
            return []
        result = self._open().query(query_embeddings=self._encode([query]),
            where={'$and': [{'document_id': document_id}, {'api_id': api_id}, {'active': True}]},
            n_results=min(top_k, len(candidates)), include=['metadatas', 'distances'])
        by_id = {c['candidate_id']: c for c in candidates}
        ranked = []
        for cid, metadata, distance in zip(result['ids'][0], result['metadatas'][0], result['distances'][0]):
            candidate = by_id.get(cid)
            if candidate is None or metadata.get('content_hash') != candidate['content_hash']:
                continue
            ranked.append(dict(candidate, semantic_distance=float(distance)))
        return ranked
