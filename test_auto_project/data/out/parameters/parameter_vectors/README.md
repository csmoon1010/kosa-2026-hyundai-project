# 기존 Parameter Chroma 인덱스 복사본

복사일: 2026-11-01
원본: `hyejung/mini_project_2/output/parameter_vectors/`
저장소 내 위치: `data/out/parameters/parameter_vectors/` (고정본 — 테스트는 임시 복사본을 연다. Chroma 는 열기만 해도 sqlite 를 고쳐 쓴다)
검색 코드: `src/tap/retrieval/chroma_index.py`

원본의 DB와 HNSW 파일을 디렉터리 전체로 복사했다. 새 임베딩을 생성하지 않았으며 원본은 수정하지 않았다. 파일별 SHA-256과 컬렉션 정보는 `copy_manifest.json`에 기록했다.

- 컬렉션: `canonical_parameters_cf5a1c85ad4d`
- 모델: `text-embedding-3-small`, 기본 1536차원
- 저장 레코드: 1816개. 현재 KB의 908개 파라미터와 개수는 다르므로 저장 레코드 전체를 그대로 쓰지 않는다.
- 검색 전 document_id와 api_id로 범위를 제한하고, 검색 후 현재 KB에 실제 존재하는 parameter_path로 상세 원문을 연결해야 한다.
- 압축 1에서 `tap.agent.kb_retrieval.ExistingChromaIndex`를 통해 Runtime에 연결했다. API·파라미터 경로와 현재 Canonical 해시를 조회 시 대조하며 불일치하면 전체 KB로 전환한다. 검색 품질의 전체 보장을 뜻하지 않는다.

## 의존성과 호출

`requirements.txt`에 원본과 같은 `chromadb==1.5.9`를 추가했다. 코드의 나머지 외부 의존성은 기존 openai·pydantic이다. 이번 복사 작업에서 패키지를 설치하거나 네트워크 임베딩 호출을 실행하지 않았다.

```python
from pathlib import Path
from tap.retrieval.chroma_index import CanonicalChromaIndex

# root 는 저장소 루트의 절대 경로다.
index = CanonicalChromaIndex(
    Path(root) / "data/out/parameters/parameter_vectors",
    model_name="text-embedding-3-small",
)
```

`search(query, document_id, api_id, candidates, top_k)`는 원본과 동일하게 현재 후보 목록을 받는다. 후보에는 candidate_id와 content_hash가 필요하다. 이 목록을 최신 JSON에서 구성하는 어댑터는 아직 추가하지 않았다. 낮은 수준의 Chroma 결과를 KB에 연결할 때도 metadata의 parameter_path와 현재 JSON의 식별자를 대조해야 한다.

문서와 질의는 같은 모델·차원을 사용해야 한다. 질의 벡터 생성에는 OPENAI_API_KEY가 필요하다. 원본 클래스는 다른 모델을 지정하면 별도 컬렉션을 생성할 수 있으므로 복사본 재사용 시 위 모델을 명시한다. `sync()`는 컬렉션을 변경하므로 자료 대응을 확인한 뒤 인덱스 갱신 시에만 사용한다.

현재 IR 생성의 압축 1 체크박스를 선택하면 복사된 인덱스를 읽는다. `ExistingChromaIndex`는 기존 컬렉션만 열며 sync()를 호출하지 않는다. 전처리 화면의 동작은 유지한다.
