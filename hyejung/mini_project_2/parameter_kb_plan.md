# Parameter KB 기본 생성·직접 입력·도메인 문서 지식 보강 작업계획서

작성일: 2026-10-24

구현 대상: `hyejung/mini_project_2/preprocessing.ipynb`의 `## 3. ParameterKB`

이 문서는 사용자 답변과 채택된 권장 방향을 반영한 구현 계획이다. 지원 입력·저장 구분·검색·검토·갱신 정책은 확정된 기준으로 사용한다. 함수·테이블은 이 기준을 구현하기 위한 설계이며, 실제 도메인 파일의 경로와 내용은 실행 시 입력받는다.

## 1. 목적과 설계 근거

Canonical Schema에 이미 추출된 요청 파라미터를 기준으로 Parameter KB의 기본 레코드를 만들고, 사용자 직접 입력과 별도 도메인 문서의 LLM 추출 두 경로로 업무 지식을 보강한다. 보강 지식은 API 규칙 또는 API 연결이 없는 COMMON 규칙으로 저장한다.

저장 대상은 Parameter KB로 한정한다. 직접 입력에서는 사용자가 `kind`를 선택하고, 문서 추출에서는 LLM이 미리 정의된 `kind` 중 하나를 판단한다. 두 경로는 같은 데이터 모델과 검증·저장 함수를 사용한다. `kind` 결정, 대상 파라미터 매칭, 규칙의 적용 범위 결정은 각각 별개의 절차다.

보강 지식 등록 시 `api_ids`가 지정되면 `kb_scope=API`, 생략되거나 None이면 `kb_scope=COMMON`으로 저장한다. COMMON 등록에서는 전체 API 검색·필드 매칭을 수행하지 않는다. 이후 전문 구성 시 선택된 API의 규칙을 우선 조회하고, 요건·도메인·업무 개념에 관련된 COMMON 규칙도 함께 검색해 보완한다.

Parameter KB는 사용자 표현과 API 요청 필드를 연결하는 근거 데이터다. 필드의 기술적 정의와 업무적 의미를 함께 제공하고, 이후 시나리오 생성 과정에서 파라미터 선택·값 해석·제약 확인에 활용한다.

참고 자료:

- [작업계획서 (1차)](https://app.notion.com/p/1-3fa467dd6f4e80f0851bc3e7730a6e0d): 파라미터 타입·필수값 추출, KB 데이터 모델, 값 출처 정의 등의 체크리스트
- [전체 아키텍처](https://app.notion.com/p/UI-3fa467dd6f4e80a190f3f7d247d5888a): 사전 작업에서 지식 생성, 시나리오 등록 단계에서 Agent가 KB와 Baseline을 참조하는 흐름
- [세부계획서](https://app.notion.com/p/UI-3f1467dd6f4e80db8677e6a7b4cefce3): 3. Canonical Schema 및 5. Parameter KB의 구조·추출·매칭 설계
- `hyejung/lecture/5. harness_core.ipynb`: `OpenAI()`와 `client.responses.create()` 호출 방식 참고
- `test_auto_project/prototype/offline-ui.html`: 관리자 규칙 입력의 항목·대상 선택, 전역·도메인·간선 적용 범위와 수동 보정 동작 참고. 이번 작업에서 HTML은 수정하지 않는다.
- `hyejung/mini_project_2/canonical_schema_plan.md`, `baseline_registration_plan.md`: 기존 전처리 산출물과 연결 규칙

노션에서 제시한 `identity / schema / knowledge / search / runtime` 구조를 따른다. 아래의 SQLite 구성, 상태 전이, 파일 입력 규약, 호출 설정 및 검증 정책은 현재 코드에 맞춘 구현 제안이다.

## 2. 현재 구현 상태와 다음 작업의 경계

### 2.1 재사용할 기존 코드

- `CanonicalParameter`: `path`, `location`, `name`, `type`, `format`, `required`, `requiredDeclared`, `enum`, `description`, `example`, XML 메타데이터 보유
- `normalize_type()`, `walk_schema()`, `build_canonical_api()`: Swagger의 요청 필드 및 기술 정보 추출
- `load_canonical_api()`: `document_id + api_id`로 Canonical JSON 조회
- `model_to_dict()`, `now_iso()`, `OUTPUT_DIR`: 직렬화·시간·출력 경로 처리
- `output/canonical_schema.db`: `api_canonical_schema` 테이블에 API별 Canonical JSON 저장
- `output/baseline.db`: 요청 XML과 기존 Baseline 검증 결과 저장

2026-10-24에 확인한 저장 JSON 기준으로 43개 API, 908개 파라미터가 있으며, 821개는 `requiredDeclared=false`다. 이 수치는 현재 스냅샷의 관찰값이며 실행 시 다시 집계한다.

### 2.2 이번에 구현할 내용

1. Canonical 파라미터를 KB 기본 레코드로 변환한다. 이 단계는 LLM을 호출하지 않는다.
2. 사용자에게 항목(`kind`)·내용·선택적 api_ids·업무 개념 또는 대상 필드·적용 범위를 입력받는 수동 등록 경로를 제공한다.
3. 별도 도메인 문서를 읽고 출처 및 청크를 만든 뒤, LLM이 Parameter KB 관련 지식과 `kind`를 추출한다.
4. api_ids 지정 시에만 지정 API의 Canonical 후보를 검색한다. 직접 선택한 정확한 대상은 LLM 매칭을 생략하고, API 지정 문서 추출 결과는 LLM으로 매칭한다. 미지정 시 COMMON의 개념·내용·근거를 저장한다.
5. 두 입력 경로에 공통으로 형식·출처·적용 범위·충돌을 검증한다. API 규칙에는 필드 참조·타입·enum 검증을 추가하고 COMMON의 API별 적합성은 전문 구성 시 확인한다.
6. `API > COMMON` 조회·병합 계약과 적용 범위별 우선순위를 명시하고, 자동 지식과 수동 보정을 분리해 보존한다.
7. API 규칙·COMMON 규칙·미해결 항목·입력 경로·범위·실행 통계를 SQLite와 조회용 JSON/표로 제공한다.

### 2.3 후속 단계로 남길 내용

- 실제 업무 API 호출, Scenario IR 생성 및 실행
- Response Outputs 추출, 이전 API 응답값의 실제 바인딩
- 사용자 요청에 대한 실제 값 생성 및 최종 파라미터 변경
- 업무 규칙의 완전한 실행 엔진, 자동 승인 UI
- Vector DB 및 임베딩 검색 운영
- PDF·DOCX·스캔 문서의 원본 파싱/OCR: 우선 텍스트 파일로 변환해 전달받는다.
- State Vocabulary·API Catalog·API Metadata 지식의 추출·분류·저장 처리기 및 전체 저장 대상 자동 라우팅
- 관리자 HTML 수정과 실제 웹 화면 구현. 노트북 입력 셀과 함수로 수동 등록 계약을 먼저 제공한다.

도메인 파일은 UTF-8 `.md`, `.txt`만 직접 지원한다. 다른 파일 형식은 입력 단계에서 지원하지 않는 형식으로 반환한다.

Baseline 저장 여부와 관계없이 KB 기본 생성은 가능해야 한다. 도메인 문서나 API 키가 없어도 기본 레코드 생성과 직접 입력·검증·저장은 가능해야 한다. OpenAI 클라이언트 초기화는 문서 추출용 셀에서 수행한다.

## 3. 전체 처리 흐름

```text
canonical_schema.db
  → 대상 API의 parameters 조회
  → identity / schema / 기본 meaning / search 생성
  → parameter_kb.db에 기본 레코드 upsert

사용자 직접 입력
  → 사용자 항목 선택으로 kind 확정 + 종류별 내용 입력
  → api_ids 지정: API 규칙, 대상 필드 선택·정확한 Canonical 복합키 연결
  → api_ids 미지정: COMMON 규칙, 업무 개념·조건·검색어 기록, API 연결 생략
  → 공통 검증 → 영향 확인 → 후보 저장 또는 명시적 채택

별도 도메인 문서(.md / .txt) + 선택적 api_ids + 적용 범위
  → 파일 읽기·해시·문서 메타데이터 등록, 변경 문서는 이전 현재본과 차이 표시
  → 제목/문단 중심 청크 분할 + 원문 위치 기록
  → Knowledge Extraction LLM: 업무 지식 및 kind 판단
  → 원문 근거 존재 검사
  → api_ids 지정: 지정 API의 후보 검색 → Parameter Matching LLM
  → api_ids 미지정: COMMON 규칙으로 준비, API 검색·매칭 생략
  → 공통 검증 + API/COMMON 저장 구분에 따른 검증
  → 후보·변경안 준비 → 사용자 검토·승인 → 현재본 반영
  → API/COMMON 조회 JSON / DataFrame / 실행 리포트 생성

후속 전문 구성(계약 정의)
  → 사용할 API + 요건 + Canonical Schema + Baseline 확인
  → 해당 API 규칙 조회 + 관련 COMMON 규칙 검색
  → COMMON의 업무 개념을 이번 전문의 필드에 한정해 매칭·적합성 검사
  → 같은 항목은 API 우선, COMMON의 미포함 내용·추가 제약은 함께 확인
  → 채택·제외·충돌과 근거를 제공 → 전문 구성·최종 검증
```

API 지정 문서 경로는 노션의 `문서 파싱 → Knowledge Extraction LLM → Parameter Retriever → Parameter Matching LLM → 저장`을 따른다. COMMON은 추출·개념 수준 검증 후 저장하고 전문 구성 시 필요한 규칙만 사용 API에 맞춘다. 직접 입력은 어느 저장 구분에서도 LLM 없이 처리한다. 초기 검색은 로컬 문자열·키워드 방식으로 만들고 품질이 부족할 때 임베딩으로 확장한다.

## 4. 입력 규약과 설정

### 4.1 Canonical 기본 생성과 보강 지식의 저장 구분

- DB: `output/canonical_schema.db`
- 원본 테이블: `api_canonical_schema`
- 기본 레코드 생성: `document_id` 필수, `canonical_api_ids`는 선택. 미지정 시 해당 문서 전체 API를 변환한다.
- KB 식별키: `(document_id, api_id, parameter_path)`
- `parameter_path`는 기존 `path` 그대로 사용한다. XML 요청을 수정할 때 사용할 `xmlPath`도 함께 보존한다.
- 같은 이름의 필드가 여러 Dataset이나 API에 있어도 경로와 API가 다르면 별개 레코드다.

기본 생성의 선택 필터를 `canonical_api_ids`로 명명하여 아래의 지식 등록용 `api_ids`와 구분한다. 기본 생성은 원본 파라미터 목록을 만드는 작업이므로 미지정 시 전체 API를 처리해도 COMMON 규칙을 생성하는 것은 아니다. 활성 간선 필드만 보는 화면은 조회 필터로 제공한다.

보강 지식 등록에는 다음 규칙을 적용한다. `api_ids` 의미는 직접 입력과 문서 추출에서 동일하며 LLM이 저장 구분을 바꾸지 않는다.

| api_ids 입력 | 저장 구분 | 등록 시 처리 |
| --- | --- | --- |
| 비어 있지 않은 API 목록 | `kb_scope=API` | canonical_document_id 필수, 지정 API의 필드에 연결·검증 |
| 키 생략 또는 None | `kb_scope=COMMON` | API 연결 없이 개념·내용·근거 저장, Canonical 문서 없이도 등록 가능 |
| 빈 목록 `[]`, 잘못된 타입, 존재하지 않는 API | 입력 오류 | COMMON으로 바꾸지 않고 오류 반환 |

API 문서 식별자는 `canonical_document_id`로 받아 `document_id` 복합키에 연결한다. API 규칙의 매칭이 실패해도 COMMON으로 자동 전환하지 않고 지정 API에 대한 미해결 항목으로 남긴다. COMMON을 나중에 특정 API 규칙으로 보정하려면 별도 명시적 API 등록을 수행하고 원본 COMMON은 보존한다.

### 4.2 도메인 문서 입력

권장 디렉터리: `hyejung/mini_project_2/domain_docs/`

지원 형식은 UTF-8 `.md`, `.txt`로 확정한다. 특정 파일 목록을 명시적으로 전달하고, 파일명만으로 적용 API를 추정하지 않는다. PDF·DOCX·HTML 등은 자동 변환하지 않는다.

```python
DOMAIN_DOCUMENTS = [
    {
        "domain_document_id": "common-policy",
        "path": PROJECT_DIR / "domain_docs" / "common_policy.md",
        "title": "공통 업무 규칙",
        "version": "v1",
        # api_ids 생략: COMMON 저장, API 검색·매칭 없음
        "application_scope": {"type": "GLOBAL", "domain_id": None, "edge_id": None},
    },
    {
        "domain_document_id": "product-policy",
        "path": PROJECT_DIR / "domain_docs" / "product_policy.md",
        "title": "상품 업무 규칙",
        "version": "v1",
        "canonical_document_id": DOCUMENT_ID,
        "api_ids": ["selectItem", "multiItem"],
        "application_scope": {"type": "DOMAIN", "domain_id": "product", "edge_id": None},
    }
]
```

위 파일·제목·범위 ID는 입력 형식 예시이며 실제 문서를 가정해 만든 업무 규칙은 없다. api_ids를 지정한 문서는 Canonical에 API가 존재하는지 확인한 뒤 지정한 목록 그대로 연결하고, 입력한 도메인/간선 범위를 그 규칙의 소속 정보로 기록한다. 별도의 LLM이나 전체 API 검색으로 소속을 재판단하지 않는다. 기존 소속 정보와 명시적으로 충돌하면 검토 대상으로 표시한다. 미지정 문서는 전체 API를 검색하지 않고 COMMON에 저장한다.

`kb_scope=API/COMMON`은 API 특정 여부이고, `application_scope=GLOBAL/DOMAIN/EDGE`는 업무 적용 문맥이다. 두 축을 구분한다. COMMON도 도메인 범위를 가질 수 있고, 기존 설계대로 간선 조건도 표현할 수 있다. 문서 전체의 범위를 입력받고 원문의 절별 조건·예외는 개별 지식에 보존한다. COMMON 등록은 범위 ID의 필수값·형식 및 개념/조건의 일관성만 검사하며 API 소속 매핑은 요구하지 않는다. 사용자에게 받은 범위 ID와 명시적 설정을 기준으로 연결하고, ID의 상세 값은 실행 입력으로 관리한다.

문서 메타데이터는 `domain_document_id`, `version`, `content_hash`, 파일 경로, 제목, 인코딩, 등록 시각을 포함한다. 해시는 원본 바이트의 SHA-256으로 계산한다. 실제 내용을 읽지 못하면 오류로 기록하고 해당 문서만 중단한다.

같은 domain_document_id의 내용이 변경되면 신규 원문을 검토 대기 개정으로 보존하고, 현재 승인본과 원문 및 추출 지식의 차이를 표시한다. 검토 전에는 기존 현재본·활성 근거를 유지한다. 사용자 승인 후 신규 개정이 현재본을 대체하는 상세 절차는 10.4에 정의한다.

### 4.3 사용자 직접 입력

저장 대상은 Parameter KB로 고정한다. 사용자는 의미·별칭·값 해석·기본값·조건부 필수 등 항목을 선택하고, 해당 항목에 필요한 구조화된 값을 입력한다. 항목 선택값을 코드가 `kind` 및 `rule_type`으로 변환하며, LLM이 이를 재분류하거나 덮어쓰지 않는다.

입력에는 `kind`, 종류별 `payload`, 선택적 `api_ids`, 개념 참조 또는 대상 선택값, `application_scope`, 작성자, 등록 사유를 포함한다. 문서 근거를 첨부할 수 있지만 필수로 요구하지는 않는다. 대신 사용자 진술과 작성자·시각·사유를 수동 입력의 출처로 보존한다.

api_ids가 있으면 지정 API의 필드명·설명으로 검색하고 API 이름·전체 경로·위치를 표시해 사용자가 정확한 대상을 선택한다. 동명 필드를 일괄 연결하지 않는다. API 미지정이면 업무 개념·관련 용어·조건·검색어를 입력하여 COMMON으로 저장하고 API 대상 선택을 요구하지 않는다.

API 등록은 노트북에서 대상 복합키 목록을 직접 입력하는 방식부터 제공할 수 있다. 지정 API의 대상이 미확정이면 `UNMATCHED / AMBIGUOUS`로 보류한다. COMMON의 targets가 비어 있는 것은 정상이며 API에 매칭되지 않았다는 이유로 미해결 처리하지 않는다. api_ids 없이 API targets를 전달하면 입력 불일치 오류로 반환한다.

### 4.4 실행 인터페이스 제안

```python
initialize_parameter_kb(document_id, canonical_api_ids=None)
enrich_parameter_kb(domain_documents, config)
register_manual_knowledge(
    kind, payload, application_scope, author, reason,
    api_ids=None, canonical_document_id=None, targets=None, concept_refs=None,
)
preview_knowledge_impact(knowledge_id)
get_parameter_kb(document_id, api_id, include_candidates=True)
search_common_knowledge(query, context, include_candidates=False)
get_effective_parameter_knowledge(document_id, api_id, requirements, context)
review_parameter_knowledge(knowledge_id, decision, reviewer, reason)
preview_document_update(domain_document_id, new_document)
approve_document_update(change_set_id, reviewer, reason)
reject_document_update(change_set_id, reviewer, reason)
```

기본 생성, 직접 입력, 문서 보강, 사용자 검토 실행 셀을 분리한다. 수동 입력·LLM 추출 모두 후보와 영향 요약을 사용자에게 보여준 뒤 명시적으로 채택한다. 검토 함수의 decision은 VERIFIED 또는 REJECTED로 제한하고 채택 시 참조·범위·충돌을 다시 검사한다. 문서 변경은 항목별 조회와 별도로 변경안 전체의 사용자 승인 절차를 거친다. 초기 노트북은 검토자·사유·승인/반려를 명시적으로 입력받아 이력을 기록하며, 실제 서비스의 사용자 신원 연동은 후속 UI 통합에서 처리한다.

### 4.5 관리자 UI와의 연결 계약

현재 관리자 UI의 `저장 대상 → 항목 → 대상 → 내용` 흐름을 참고하되 이번 처리기는 Parameter KB만 받는다. 다른 저장 대상을 받으면 명시적으로 지원 범위 밖임을 반환한다. 문서에서도 Parameter KB 관련 지식만 추출하고, 다른 저장 대상으로 자동 전송하지 않는다.

현재 UI처럼 API 선택이 없는 입력은 COMMON으로 전달하고, 대상 필드명은 API 경로가 아닌 업무 용어/개념 참조로 보존한다. API 규칙을 입력하려면 연동 호출에서 api_ids를 명시하고 정확한 Canonical 대상도 전달해야 한다. 적용 지점은 application_scope로 전달한다. 전사/도메인 메뉴 위치만으로 API/COMMON을 바꾸지 않으며, 이번 작업에서 UI를 수정하지 않는다.

## 5. Parameter KB 데이터 모델

### 5.1 기본 레코드

| 영역 | 주요 필드 | 생성 및 처리 방법 |
| --- | --- | --- |
| identity | `document_id`, `api_id`, `parameter_path`, `parameter_name`, `location` | Canonical 복사, 복합키로 식별 |
| schema | `type`, `format`, `required`, `required_declared`, `enum`, `example` | Canonical 값 보존 |
| schema | `xml_name`, `xml_path`, `xml_attribute` | 기존 XML 메타데이터 보존 |
| schema | `required_state` | 명시 여부를 반영한 `REQUIRED / OPTIONAL / UNSPECIFIED` |
| knowledge | `display_name`, `description` | Canonical 설명에서 기본 후보 생성, 출처 기록 |
| knowledge | `aliases`, `value_mappings`, `defaults`, `rules`, `dependencies` | 초기에는 빈 배열, 직접 입력·문서 추출로 보강 |
| search | `search_text`, `embedding_version` | 식별정보·설명으로 생성, 임베딩 전에는 버전 null |
| runtime | `retrieval_count`, `selected_count`, `successful_usage_count`, `failed_usage_count` | 초기 0, 후속 실제 사용 이벤트로 갱신 |
| provenance | Canonical JSON 해시, 원본 문서 ID, `sourceRef`, 변환 경고 | 출처·갱신·재검증 기준 |

필수 여부 미명시는 기존 권장안대로 required_declared=false이면 UNSPECIFIED로 보존하고, 선언이 있으면 required에 따라 REQUIRED / OPTIONAL로 설정한다. UNSPECIFIED는 원본 선언 유무를 보존하는 KB 내부 표식이며 OpenAPI의 표준 상태나 오류가 아니다. requiredDeclared는 부모 schema에 required 선언이 있는지 나타내는 현재 코드의 표식이며 조합 스키마·조상 조건까지 평가한 최종 판정은 아니다. 도메인 문서의 조건부 필수는 별도 RULE로 보강한다.

`requestBodyRequired`는 API 수준 정보로 별도 제공한다. body 전체가 필수라고 해서 모든 내부 필드를 필수로 바꾸지 않는다. 조건부 필수성은 업무 규칙으로 별도 관리한다.

Canonical `description`은 기존 코드에서 `example`의 괄호 앞 문구로 보완될 수 있다. 따라서 이를 무조건 업무적으로 검증된 의미라고 표시하지 않는다. 원본 `swagger_raw.json`과 비교해 직접 명시인지 보완된 설명인지 확인하고, 구분할 수 없으면 `CANONICAL_DERIVED` 출처의 후보로 기록한다. 필드명 자체는 검색어로 사용할 수 있지만 임의의 한글 의미를 생성하지 않는다.

이 절의 `knowledge`는 아래 5.2의 API 지식 레코드를 연결해 제공하는 조회 구조다. 한 파라미터에 의미·별칭·기본값·규칙이 여러 개 연결될 수 있고, 개별 지식마다 출처·범위·채택 상태를 따로 관리한다. COMMON은 이 기본 레코드에 억지로 연결하지 않고 독립적으로 저장·조회한다. API별 통합 조회에서는 관련 COMMON 후보를 별도 목록으로 함께 반환한다.

### 5.2 직접 입력·문서 추출 지식의 공통 구조

| 필드 | 설명 |
| --- | --- |
| `knowledge_id` | 중복 방지를 위한 안정적인 지식 식별자 |
| `kb_scope` | 등록 api_ids 유무로 코드가 결정하는 `API / COMMON` |
| `api_ids`, `canonical_document_id` | API 규칙의 지정 대상. COMMON은 api_ids=None이며 Canonical 문서 없이 저장 가능 |
| `kind` | `MEANING / ALIAS / VALUE_MAPPING / DEFAULT_VALUE / RULE / DEPENDENCY` |
| `entry_method` | `MANUAL / DOCUMENT_LLM / CANONICAL` 입력 경로 |
| `kind_origin` | `USER_SELECTED / LLM_CLASSIFIED / CANONICAL_DERIVED` 분류 결정 주체 |
| `source_term` | 사용자 또는 문서에 제시된 업무 용어 |
| `payload` | 종류별로 검증된 구조화 내용 |
| `source` | `USER_DEFINED / DOMAIN_DOCUMENT / SWAGGER / CANONICAL_DERIVED` 등 출처 |
| `confidence` | LLM의 추출·매칭 점수. 직접 입력에는 null을 사용하고 임의의 1.0을 부여하지 않음 |
| `status` | 후보·확정·반려·충돌·미매칭 등 상태 |
| `source_evidence` | 문서 인용 또는 사용자 진술. 입력 경로에 따라 서로 다른 근거 모델로 검증 |
| `targets` | API 규칙의 정확한 파라미터 복합키 목록. COMMON은 빈 배열 |
| `concept_refs`, `search_text` | 업무 개념·관련 용어·검색어. COMMON의 대상/조건 참조 및 검색에 사용 |
| `application_scope` | `GLOBAL / DOMAIN / EDGE`와 필요한 domain_id·edge_id |
| `author`, `created_at`, `reason` | 직접 입력의 작성자·시각·등록 사유 |
| `extraction_run_id`, `prompt_version` | LLM 추출 시 기록, 직접 입력에는 null |
| `evidence_count` | 중복 제거한 근거 수 |

종류별 `payload`는 Pydantic 모델로 분리한다. 저장 JSON의 유연한 표현과 LLM 출력 스키마를 구분하며, LLM에게 자유로운 Python 코드나 임의 실행 표현식을 받지 않는다.

- `MEANING`: 대표 용어와 설명. `display_name / description` 중 어느 역할인지 구분
- `ALIAS`: 표현, 대응 의미, `alias_type=NATURAL_LANGUAGE / FIELD_NAME`. 자연어 별칭과 다른 필드명의 대응 관계를 구분하고, 필드명 별칭만으로 API 간 값 바인딩을 확정하지 않음
- `VALUE_MAPPING`: `mapping_type=CODE_MEANING / EXPRESSION_TO_VALUE`, 코드·설명 또는 표현·변환 값, 단위·조건. 코드 설명과 실제 값 변환을 구분
- `DEFAULT_VALUE`: 타입이 보존된 기본값, 필요한 조건. 적용 범위는 공통 `application_scope`에 저장하고 Canonical example·Baseline과 구분
- `RULE`: `rule_type`, `condition`, `constraint`, 설명
- `DEPENDENCY`: 조건의 source 필드와 결과의 target 필드를 모두 포함

초기 지원 규칙은 REQUIRED_IF, MIN_VALUE, MAX_VALUE, ALLOWED_VALUES, LENGTH, PATTERN, OTHER로 하고 연산자는 EQ / NE / IN / GTE / LTE / PRESENT로 제한한다. OTHER는 검토용 설명만 저장하고 실행 대상에서 제외한다. 복합 조건은 AND/OR를 사용하며 최대 중첩 깊이를 2로 둔다. 이를 넘거나 표현할 수 없는 규칙은 원문과 함께 미해결로 남긴다. Python 코드나 자유 표현식은 실행하지 않는다.

API 규칙의 dependency는 참조되는 모든 파라미터를 매칭·검증해야 한다. COMMON은 조건과 결과의 개념 참조를 일관되게 저장하며 API 경로를 요구하지 않는다. 실제 전문에 적용할 때는 모든 개념을 해당 API 필드/컨텍스트에 연결하고 검증한다. 일부 참조만 해석된 규칙을 실제 전문에 적용하지 않는다.

사용자 항목과 저장 구조의 대응:

| 사용자 선택 항목 | kind 및 세부 구조 | 문서 추출 시 |
| --- | --- | --- |
| 의미 | `MEANING` | LLM이 명시된 대표 의미·설명을 분류 |
| 별칭 | `ALIAS` + alias_type | LLM이 자연어/필드명 별칭을 구분 |
| 값 해석 | `VALUE_MAPPING: CODE_MEANING` | LLM이 코드와 설명의 관계를 추출 |
| 값 변환 | `VALUE_MAPPING: EXPRESSION_TO_VALUE` | LLM이 명시된 변환 관계·단위를 추출 |
| 기본값 | `DEFAULT_VALUE` | 문서에서 기본 사용값임이 명시된 경우만 추출 |
| 조건부 필수 | `RULE: REQUIRED_IF` | 조건 필드와 필수 대상 필드를 각각 추출 |
| 기타 제약/의존성 | `RULE` 또는 `DEPENDENCY` | 허용된 규칙 구조에 맞춰 분류 |

직접 선택한 kind와 payload가 맞지 않으면 입력 오류로 반환하고 사용자가 수정한다. LLM 분류 결과가 불명확하거나 표현할 수 없는 내용이면 원문과 함께 검토 목록에 남긴다. `REQUIRED_IF`는 RULE로 한 번만 저장하고 조건·대상 참조를 연결하며 같은 내용을 DEPENDENCY로 중복 생성하지 않는다.

근거 모델은 `DOCUMENT_QUOTE`(문서 ID·해시·청크·절·인용·원문 위치)와 `USER_STATEMENT`(직접 입력 원문·작성자·시각·사유)로 구분한다. 직접 입력이 문서를 인용하면 문서 근거도 추가하고 그 인용은 동일하게 검증한다.

### 5.3 값 출처 정의와 이번 단계의 범위

지식의 출처와 실제 요청값의 출처를 구분한다.

| 구분 | 예시 | 이번 단계 처리 |
| --- | --- | --- |
| 지식 출처 | `SWAGGER`, `CANONICAL_DERIVED`, `DOMAIN_DOCUMENT`, `USER_DEFINED` | 근거와 함께 저장 |
| 실행값 출처 | `BASELINE`, `USER_INPUT`, `PREVIOUS_RESPONSE`, `RULE_DERIVED` | 종류와 참조 모델만 정의 |

Canonical의 `example`은 실행 가능한 확정값으로 간주하지 않는다. `협력사코드(타입:string, 예:003766)`처럼 설명이 섞인 문자열도 원문 그대로 보존한다. 코드값 `003766`을 숫자로 바꾸지 않는다.

Baseline 값은 기존 Baseline DB를 참조하는 방식으로 연결할 수 있다. 이전 응답값의 실제 경로와 바인딩은 Response Outputs 및 시나리오 생성 단계에서 결정한다. 근거 없이 필드마다 실행값 출처를 확정하지 않는다.

채택된 `DEFAULT_VALUE`는 실행값 출처 `RULE_DERIVED`의 기본값 규칙으로 참조할 수 있다. 이번에는 규칙을 저장·조회하는 계약까지만 만들고, 실제 요청값 결정과 적용은 시나리오 단계에서 수행한다.

### 5.4 API/COMMON 저장 구분과 업무 적용 범위

API/COMMON은 지식의 저장 구분이며 GLOBAL/DOMAIN/EDGE와 다른 축이다. 같은 SQLite DB 안에서 kb_scope로 논리적으로 분리한다.

| 저장 구분 | 등록 시 필요한 대상 | 저장 목적 |
| --- | --- | --- |
| `API` | 지정 api_ids와 Canonical 필드 연결 | 특정 API 전문에 우선 적용할 규칙 |
| `COMMON` | 업무 개념·용어·조건·근거, API 연결 없음 | API 규칙을 보완할 공통 지식 |

| 범위 | 필수 식별정보 | 의미 |
| --- | --- | --- |
| `GLOBAL` | type | 도메인/간선 제한 없음. 실제 관련성과 필드 적합성은 조회 시 확인 |
| `DOMAIN` | type, domain_id | 지정한 도메인의 문맥에서만 적용 |
| `EDGE` | type, domain_id, edge_id | 지정한 간선에서만 적용 |

COMMON에는 등록 시 모든 API를 찾아 연결하거나 가짜 공통 API·parameter_path를 만들지 않는다. GLOBAL도 모든 동명 필드에 자동 적용한다는 뜻은 아니다. COMMON은 범위 ID/개념을 검증하고, API 규칙은 사용자가 지정한 API 목록·업무 범위를 소속으로 연결한다. 전문 구성에서는 이 명시적 소속과 현재 문맥을 기준으로 필요한 COMMON만 검토한다. 문맥이 불명확하거나 필드 매칭이 모호하면 해당 전문에 대한 적용을 보류한다.

같은 항목의 대체 가능한 기본값·값 해석은 먼저 `API > COMMON`을 적용하고, 같은 저장 구분 안에서는 `간선 > 도메인 > 전역`을 적용한다. 따라서 같은 항목에서 API/GLOBAL과 COMMON/EDGE가 모두 관련되어도 API 규칙이 우선이다. 채택 상태·조건·타입·문맥 적합성을 통과한 후보만 비교한다.

수동 보정 우선순위는 같은 kb_scope·업무 범위·역할 안에서 적용하며 COMMON 수동 입력이 API 규칙을 앞서지 않는다. 작성자 권한·사유·이전값·영향 확인을 남긴다. 이 우선순위는 Canonical 타입·필수 조건·enum을 무시하거나 기존 사용자 명시값을 덮어쓰는 권한을 뜻하지 않는다. 규칙 기본값은 기존 프로젝트 계약대로 Baseline보다 우선하고 실제 요청값 선택은 후속 전문 구성 단계에서 수행한다.

### 5.5 전문 구성 시 API 우선·COMMON 보완 조회

이번 단계는 조회·병합 결과와 검증 계약을 제공한다. 실제 요건 해석·전문 생성·업무 API 실행은 후속 단계다. 이미 선택된 API를 대상으로 하며 COMMON 조회 때문에 실행할 API를 다시 탐색하지 않는다.

1. 선택 API의 Canonical Schema·Baseline과 사용자가 명시한 요건, 도메인/간선 문맥을 받는다.
2. 채택된 API 규칙을 조회한다. API 규칙이 있더라도 COMMON 검색을 생략하지 않는다.
3. 사용자가 지정한 API 목록에서 현재 API를 확정하고, COMMON은 현재 도메인/간선·채택 상태·관련 개념으로 후보 목록을 먼저 좁힌다. 그 목록 안에서 요건·API 설명·파라미터 의미·별칭을 이용해 Top-K 검색한다. 필요한 규칙만 매칭하고 적용 조건을 확인한다.
4. 필요한 COMMON만 이번 전문의 필드에 매칭한다. API 전체에 영구 연결하지 않고 이번 조회/구성 결과에만 매칭 경로와 근거를 남긴다. 모호한 매칭은 보류한다.
5. 동일 항목의 기본값·값 해석은 API 규칙 우선으로 선택하고, API에 없는 항목은 COMMON으로 보완한다. 별칭은 중복 제거해 함께 활용할 수 있다.
6. COMMON의 추가 제약·조건부 필수도 확인한다. 양립 가능한 제약은 함께 검증하고, 제약이 충돌하면 단순 우선순위만으로 무시하지 않고 검토 대상으로 반환한다.
7. Canonical 타입·필수 조건·enum을 최종 확인하고, 선택·보완·제외·미매칭·충돌 결과와 지식 ID/출처를 반환한다.

일반 API 조회는 API 규칙과 관련 COMMON 후보를 구분해 반환한다. `get_effective_parameter_knowledge()`는 `selected`, `common_supplements`, `shadowed`, `unresolved`, `conflicts` 및 각 판정의 이유를 제공한다. COMMON 규칙 자체가 다른 API에도 유효할 수 있으므로 특정 전문의 미매칭·충돌 때문에 원본 COMMON 전체를 무효화하지 않는다.

## 6. Canonical에서 기본 레코드 생성

1. 대상 API를 조회하고 `(document_id, api_id, path)` 중복을 검사한다.
2. 각 파라미터의 식별정보·기술정보·XML 경로·원본 참조를 복사한다.
3. 필수 여부의 명시 유무와 타입 정규화 경고를 보존한다.
4. 원본에 명시된 설명과 변환 중 보완된 설명을 가능한 범위에서 구분한다.
5. 별칭·기본값·규칙·의존성은 빈 배열로 초기화한다.
6. API 이름, 파라미터명, 설명, 경로를 결합해 기본 `search_text`를 만든다.
7. JSON/Pydantic 검증 후 기본 레코드를 upsert한다.

재실행 시 기존 API/COMMON 지식·수동 보정·검토 상태·사용 통계를 초기화하지 않는다. Canonical이 바뀌면 변경 필드에 연결된 API 지식을 `REVALIDATION_REQUIRED`로 표시한다. 삭제된 필드는 `active=false`로 남기고 관련 API 지식을 조회·실행 대상에서 제외한다. API 일부만 처리할 때는 해당 범위만 비교한다. 특정 API의 변경만으로 COMMON 원본을 무효화하지 않으며 이전 전문의 COMMON 매칭 결과만 재검증한다.

## 7. 도메인 문서 읽기와 근거 추적

### 7.1 청크 생성

- Markdown 제목과 문단, 표, 목록을 우선 단위로 사용한다.
- 청크에 문서 제목·상위 절 제목을 포함한다.
- 초기 청크 크기는 약 3,000자, 겹침은 300자로 두고 실제 규칙 길이에 따라 조정한다.
- 조건과 결론, 표의 헤더와 값이 분리되지 않도록 한다. 크기 한도를 넘는 문단은 추가 분할하고 인접 청크를 함께 확인할 수 있게 한다.
- `chunk_id`, 시작·종료 줄, 원문 구간의 문자 offset을 기록한다.
- 바이트 해시용 원본과 줄 번호를 계산하는 디코딩 텍스트를 보존하고 줄바꿈 정규화 규칙을 고정한다.

### 7.2 근거 검증

LLM은 원문 인용과 청크 ID를 반환한다. 문서 ID·해시·실제 위치는 코드가 신뢰할 수 있는 입력 메타데이터로 채운다.

- 인용이 지정 청크의 실제 텍스트에 존재하는지 검사한다.
- 줄 번호는 모델 출력값을 믿지 않고 인용의 위치로 계산한다.
- 같은 문장이 여러 곳에 있어 위치를 확정하지 못하면 추가 문맥을 요구하거나 검토 대상으로 남긴다.
- 존재하지 않는 인용은 지식으로 채택하지 않고 `INVALID_EVIDENCE`로 기록한다.
- 원문 포함 검사는 최소 검증이다. 인용이 해당 규칙을 실제로 뒷받침하는지는 검토 항목으로 유지한다.
- 문서 내용은 분석 대상 데이터로 전달하고 모델의 동작 지시로 취급하지 않는다.

## 8. KIND 결정과 파라미터 매칭

| 입력 경로/저장 구분 | kind 결정 | 등록 시 대상 결정 | LLM 호출 |
| --- | --- | --- | --- |
| 직접 입력/API | 사용자 선택, `USER_SELECTED` | 지정 API의 정확한 복합키 선택 | 없음 |
| 직접 입력/COMMON | 사용자 선택, `USER_SELECTED` | 업무 개념·조건 참조, API 대상 없음 | 없음 |
| 도메인 문서/API | LLM 판단, `LLM_CLASSIFIED` | 지정 API 후보 검색 후 LLM 매칭 | 추출·매칭의 2단계 |
| 도메인 문서/COMMON | LLM 판단, `LLM_CLASSIFIED` | 개념·조건·근거 저장, API 검색 생략 | 추출 단계만 |

아래 8.1은 모든 문서 입력에, 8.2~8.3은 api_ids가 지정된 문서의 API 연결에 적용한다. COMMON 문서는 8.1 후 바로 8.4 검증·저장으로 간다. 직접 입력은 4.3 후 8.4로 연결한다. kb_scope는 코드가 입력 계약에 따라 결정하며 LLM이 바꾸지 않는다.

### 8.1 1차 호출: Knowledge Extraction

청크와 문서의 업무 범위를 입력한다. LLM은 Parameter KB 관련 내용만 추출하고 각 지식에 허용된 `kind` 및 종류별 payload를 부여한다. State Vocabulary·Catalog·Metadata 대상으로 자동 분류·저장하지 않는다. 하나의 문장에 서로 다른 지식이 있으면 근거를 공유하는 별도 항목으로 분리한다.

- 파라미터 의미와 별칭
- 필수 조건, 허용값, 값 제약
- 자연어 표현과 코드/값의 변환 관계
- 원문에 명시된 기본값 및 적용 범위·예외
- 다른 파라미터와의 의존성
- 원문 근거 및 조건·예외

이 단계에서는 실제 파라미터 ID를 확정하지 않는다. 문서에 없는 별칭·기본값·업무 규칙을 만들지 않으며, 관련 내용이 없으면 빈 배열을 반환한다. 예시값·최빈값을 근거 없이 기본값으로 바꾸지 않는다. `상품코드`라는 표현만으로 `slitmCd`를 확정하지 않는다. kind가 불명확하면 임의의 enum으로 확정하지 않고 unresolved 항목에 원문과 분류 불가 사유를 남긴다.

### 8.2 후보 검색

API 저장으로 결정된 입력만 처리한다. canonical_document_id와 지정 api_ids 목록으로 먼저 후보를 제한한 뒤 name·설명·API 이름·경로·채택된 별칭으로 Top-K 검색한다. 입력한 업무 범위를 소속으로 연결하고 이미 알려진 충돌만 검토 대상으로 표시한다. 매칭 실패 시 전체 API로 검색을 넓히거나 COMMON으로 전환하지 않는다. header와 XML 구조용 attribute도 기본 KB에 보존하되 문맥에 따라 검색 우선순위를 조정한다.

검색 방식은 목록 사전 제한 후 로컬 문자열·토큰 점수 기반 Top-K로 확정하고 초기 K는 10으로 둔다. 한글 공백·표기 차이를 고려하며 점수가 낮거나 동점이면 확정 매칭으로 간주하지 않는다. 검색어·K를 조정하더라도 지정 api_ids 내부에서만 검색하고 해결되지 않으면 UNMATCHED로 남긴다. 검토되지 않은 별칭은 확정 근거로 사용하지 않는다. COMMON 조회도 문맥으로 좁힌 후보 목록 안에서 Top-K를 구하고 필요한 규칙만 필드에 매칭한다. Vector DB/임베딩은 이번 구현에 도입하지 않는다.

### 8.3 2차 호출: Parameter Matching

추출 지식·원문 문맥·후보 목록을 입력한다. 후보별로 API ID, 전체 경로, location, 타입, 설명, XML 경로를 제공한다.

출력은 `MATCHED / NONE / AMBIGUOUS`와 후보 ID 목록, 매칭 점수, 짧은 근거다. 단순 지식은 하나의 대상, 의존성은 각 참조 필드에 대한 대상을 반환한다. 하나의 정책이 여러 API에 적용될 때는 적용 범위를 검증한 별도 연결을 만든다.

- 후보 목록에 없는 새 필드나 경로를 만들지 않는다.
- 후보 ID는 코드가 실제 복합키로 역참조한다.
- 필드명 유사성만으로 선택하지 않는다.
- 후보가 비슷하거나 대응 필드가 없으면 매칭하지 않는다.
- 초기 점수 기준 0.90은 검토 우선순위와 보류 판정에만 사용한다. 높은 점수만으로 VERIFIED로 승격하지 않는다.

### 8.4 두 입력 경로의 합류

직접 입력과 문서 추출 결과를 `ParameterKnowledgeInput` 공통 모델로 변환한다. kb_scope·kind·payload·targets/concept_refs·application_scope·출처를 같은 검증 함수에 전달한다. API 모델은 지정 API·필드 참조를, COMMON 모델은 개념·조건의 일관성을 요구한다. 동일한 kind별 payload 규격을 유지하면서 API에 의존하는 검증은 API 저장 또는 후속 전문 구성 시 수행한다.

여러 API가 지정된 규칙은 대상별 매칭·검증 결과를 남긴다. 일부 대상에서 참조·타입·범위·enum이 충돌하면 항목을 보류하고 사용자가 대상별로 분리해 검토할 수 있게 한다. COMMON은 API가 연결되지 않은 상태로도 정상 채택할 수 있다. 전문 구성 시 COMMON 일부 참조만 매칭되면 그 규칙의 적용을 보류하고, 해당 전문의 unresolved 결과로 남긴다.

## 9. client.responses.create() 기반의 단순 LLM 호출

### 9.1 채택할 구조

강의와 동일하게 .env를 load_dotenv/find_dotenv로 읽고 OPENAI_DEFAULT_MODEL의 default model을 사용한다. 모델명을 코드에 고정하거나 다른 모델로 대체하지 않는다. OpenAI()와 client.responses.create(), store=False 호출 방식을 유지한다. OPENAI_API_KEY도 환경변수로 제공한다.

Python 코드가 문서 읽기·청크별 지식 추출 후 kb_scope에 따라 처리 순서를 제어한다. API 문서는 후보 검색·파라미터 매칭 후 저장하고 COMMON 문서는 이를 생략하여 저장한다. 추출과 매칭은 정해진 두 종류의 LLM 호출이며 COMMON 등록은 추출만 사용한다. 청크별 처리는 일반 반복문으로 구현한다.

이 호출 방식은 도메인 문서 입력 경로에만 적용한다. 직접 입력의 kind 선택·대상 선택·검증·저장은 일반 Python 함수로 처리하며 API 키 없이 실행할 수 있게 한다.

에이전트 하네스 코어, 모델의 도구 선택·호출 루프, 대화 이력 누적, 별도 Runtime·ToolRegistry·Policy 계층은 구현하지 않는다. LLM 호출 관리에는 사용량·시간 기록, SDK 기본 재시도, timeout만 둔다. 실행 전체의 토큰·시간·호출 횟수 예산이나 별도 재시도 루프는 만들지 않는다.

로컬 `hyejung/requirements.txt`에는 `openai==2.52.0`, `python-dotenv==1.2.3`, `pydantic==2.13.4`가 명시되어 있다. 실제 설치 버전과 선택 모델의 기능 지원 여부는 구현 시 확인한다. API 키의 값은 노트북 출력에 표시하지 않는다.

필요한 프롬프트와 출력 스키마는 단계별 상수로 정의하고, `LLM_CONFIG`에는 timeout을 둔다. 지식의 근거·타입·충돌 검증은 기존 계획대로 일반 Python 함수에서 수행한다.

### 9.2 Structured Outputs 적용

Responses API의 `text.format`에 JSON Schema를 지정한다. 강의의 자유 텍스트 최종 응답을 지식 모델에 맞는 JSON으로 바꾸는 방식이다. 공식 근거: [Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

다음은 호출과 기록 방식의 설계 예시다. 공통 함수는 API를 호출하고 응답을 반환하며, 결과의 완료 상태 확인과 Pydantic 검증은 호출하는 단계에서 수행한다.

```python
import json
import os
import time
from dotenv import load_dotenv, find_dotenv
from openai import OpenAI

load_dotenv(find_dotenv(".env", usecwd=True), override=True)
MODEL = os.environ["OPENAI_DEFAULT_MODEL"]
LLM_CONFIG = {"timeout_seconds": 60.0}  # 확정된 초기 timeout
client = OpenAI(timeout=LLM_CONFIG["timeout_seconds"])  # SDK 기본 재시도 유지
LLM_CALL_RECORDS = []

# 정해진 입력과 스키마로 LLM을 호출하고 사용량·경과 시간을 기록한다.
def call_structured_llm(instructions, payload, schema_name, output_schema):
    started = time.perf_counter()
    response = None
    try:
        response = client.responses.create(
            model=MODEL,
            instructions=instructions,
            input=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            text={"format": {
                "type": "json_schema", "name": schema_name,
                "strict": True, "schema": output_schema,
            }},
            store=False,
        )
        return response
    finally:
        usage = response.usage if response is not None else None
        LLM_CALL_RECORDS.append({
            "stage": schema_name,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "input_tokens": usage.input_tokens if usage is not None else None,
            "output_tokens": usage.output_tokens if usage is not None else None,
            "total_tokens": usage.total_tokens if usage is not None else None,
        })

response = call_structured_llm(
    EXTRACTION_INSTRUCTIONS, payload,
    "knowledge_extraction", EXTRACTION_JSON_SCHEMA,
)

# completed/refusal/incomplete 여부를 먼저 확인한 뒤 파싱한다.
result = KnowledgeExtractionResult.model_validate_json(response.output_text)
```

LLM용 JSON Schema는 strict 모드가 지원하는 범위로 작성한다. object는 `additionalProperties=false`, 속성은 required에 포함하되 선택값은 null 허용으로 표현한다. 자유로운 `dict[str, Any]`를 그대로 전달하지 않고, 규칙·변환·참조를 타입이 있는 모델로 정의한다. Pydantic 스키마를 활용하더라도 API 지원 범위 검사를 별도로 수행한다.

구조화 출력은 JSON 형식 준수를 돕는다. 업무 의미의 정확성과 근거의 타당성은 별도 검증한다. `refusal`, `incomplete`, 빈 출력, 형식 검증 실패를 정상적인 빈 지식 결과와 구분한다. 매칭 단계는 동일한 함수에 매칭용 instructions와 schema를 전달한다. 위 예시의 파싱 전 주석에 해당하는 완료 상태 확인은 각 단계에서 구현한다.

### 9.3 사용량·시간 기록

`LLM_CALL_RECORDS`에 추출/매칭 단계명, 입력·출력·전체 토큰, 호출 경과 시간만 기록한다. `time.perf_counter()`로 측정한 경과 시간에는 SDK 내부 재시도 및 대기 시간도 포함된다.

실행 종료 시 호출 수, 반환된 usage의 토큰 합계, 호출 경과 시간 합계와 전체 처리 시간을 간단히 출력하고 리포트에 포함한다. 사용량이 반환되지 않은 실패 호출은 토큰을 null로 남기고 합계에서 제외한다. 반환된 usage의 합계는 확인 가능한 사용량이며 실패한 내부 시도까지 포함한 완전한 과금 내역으로 간주하지 않는다. 가격표 기반 비용 계산과 상세 트레이스 시스템은 추가하지 않는다.

### 9.4 SDK 기본 재시도와 timeout

- `OpenAI()` 생성 시 `max_retries`를 지정하지 않아 SDK 기본 재시도 정책을 사용한다. 별도의 재시도 반복문이나 backoff 함수를 만들지 않는다.
- 공식 Python SDK 문서 기준으로 연결 오류와 일부 일시적 HTTP 오류는 기본 2회 재시도한다. 실제 설치 버전의 동작은 구현 시 확인한다.
- timeout 초기값은 60.0초로 확정한다. SDK 기본 재시도는 유지하며 SDK 재시도·대기까지 포함한 함수 전체 시간이 반드시 60초 이내라는 의미는 아니다.
- SDK 재시도 후에도 호출에 실패하면 해당 처리 항목의 오류를 기록한다. 기존 확정 지식은 유지하고 실패한 청크/항목은 후속 실행에서 다시 처리할 수 있게 한다.
- 응답이 반환되었더라도 `refusal`, `incomplete`, 형식 오류, 근거 없는 매칭은 실패 또는 보류로 처리한다. 결과를 바꾸기 위한 자동 재호출은 하지 않는다.

공식 근거: [OpenAI Python API library — Retries / Timeouts](https://developers.openai.com/api/reference/python).

## 10. 검증·충돌·채택 정책

### 10.1 검증 순서

1. 문서 경로는 응답 완료 상태 확인, 두 경로 모두 kind·payload의 Pydantic 형식 검증
2. 문서 인용의 실재·위치 또는 직접 입력의 작성자·진술·시각·사유 검증
3. api_ids 입력에 따른 API/COMMON 구분 검사. API는 지정 API·Canonical 대상 존재 확인, COMMON은 targets가 없고 개념 참조가 있는지 확인
4. GLOBAL/DOMAIN/EDGE 범위 ID 확인. API 지정 입력은 존재하는 지정 API와 입력 범위를 그대로 소속으로 연결하고, COMMON은 ID/개념만 검증
5. 값·단위·연산자의 구조와 자체 일관성 검증. API 저장은 Canonical 타입·enum도 검사
6. 조건부 필수·의존성의 참조 검증. API는 실제 필드, COMMON은 개념·조건 참조를 검사
7. 동일 kb_scope·업무 범위의 기본값 및 기존 확정 지식과의 충돌 검사. COMMON의 특정 API 적합성은 전문 구성 시 검사
8. 지식·근거 중복 제거 및 기존값·영향 대상 요약
9. 입력 경로와 검토 결과에 따라 상태를 결정해 공통 저장 함수로 반영

예를 들어 API의 string 코드에 대한 숫자 범위 규칙, enum에 없는 코드로의 변환은 충돌로 처리한다. COMMON은 특정 API 타입·enum을 등록 조건으로 삼지 않지만 단위가 불명확하거나 내용 자체가 모순인 규칙은 보류한다. 조건부 필수 규칙은 schema.required를 덮어쓰지 않고 knowledge.rules에 보존한다.

값 해석의 코드 설명을 등록하는 것과 해당 코드를 API의 허용값에 추가하는 것은 별개다. CODE_MEANING은 의미 정보이며 Canonical enum을 확장하지 않는다. 전문에 사용하려는 기본값·변환·규칙이 해당 API의 enum 밖이면 출처가 API/COMMON 중 무엇이든 적용하지 않고 충돌을 반환한다. 직접 입력도 구분자 확인만으로 적용하지 않고 저장 구분에 따른 검증을 통과해야 한다.

### 10.2 상태

| 상태 | 의미 | 기본 제공 범위 |
| --- | --- | --- |
| `CANDIDATE` | 공통 검증을 통과했지만 아직 채택되지 않은 수동/추출 지식 | 검토 화면/표에서 제공 |
| `VERIFIED` | 명시적인 검토를 거쳐 채택. COMMON은 API별 적용 검증이 완료되었다는 의미가 아님 | 기본 검색·후속 매핑 근거로 제공 |
| `UNMATCHED` | API 규칙의 대응 필드 없음 또는 일부 참조 미해결. COMMON의 API 미연결은 정상 | 보류 목록 |
| `AMBIGUOUS` | 후보 간 우열이 불명확 | 보류 목록 |
| `CONFLICT` | 스키마·문서·기존 지식과 충돌 | 충돌 목록 |
| `REJECTED` | 검토 반려 | 이력 조회 |
| `REVALIDATION_REQUIRED` | 원본 문서 또는 Canonical 변경 | 기본 사용에서 제외 |

원본에 명시된 기술 메타데이터는 SWAGGER 출처로 사용하며 업무 의미까지 검증되었다는 뜻은 아니다. API/COMMON의 수동 입력·LLM 추출 지식은 검증 후 사용자 검토 절차를 거쳐 채택한다. 검토 화면 또는 노트북 표에는 내용·대상/개념·범위·근거·충돌·영향을 표시한다. 사용자가 승인하면 VERIFIED, 반려하면 REJECTED로 기록하고 검토 전에는 CANDIDATE를 유지한다. 직접 입력자는 자신의 입력을 명시적으로 검토·승인할 수 있으며 별도 두 번째 검토자를 필수로 두지 않는다. 검증 실패나 미해결 참조를 승인만으로 통과시키지 않는다.

`include_candidates=true` 조회에서도 상태를 표시하고 실행 가능 지식과 섞지 않는다. 승인본에 이미 포함된 파라미터가 보정으로 달라지면 변경 내용을 후속 시나리오 재확인에 제공하며, KB 저장만으로 기존 승인본을 변경하지 않는다.

같은 문서의 새 개정은 10.4의 차이 검토와 사용자 승인 후 현재본을 교체한다. 서로 다른 문서가 같은 kb_scope·업무 범위에서 충돌하면 최신 시각만으로 우열을 정하지 않고 사용자에게 차이와 근거를 보여주어 명시적으로 해소한다. API/COMMON 간 대체 가능한 기본값·값 해석 차이는 API 우선으로 처리하되 제약 충돌은 검토 대상으로 반환한다. 특정 API와 다르다는 이유만으로 COMMON 원본 전체를 반려하지 않는다.

### 10.3 수동 보정과 변경 이력

수동 보정은 원본 Canonical이나 자동 지식의 payload를 덮어쓰지 않고 별도 지식 레코드로 저장한다. 명시적 보정은 supersedes_id로 이전 항목을 참조하고 사유·검토자·영향 범위를 남긴다. 같은 kb_scope·업무 범위·역할에서 수동 의미/코드 설명을 우선 표시할 수 있지만 API/COMMON 우선순위를 역전시키지 않는다. 원본값과 출처도 조회할 수 있어야 한다.

별칭은 채택된 관련 항목을 중복 제거해 모으고, 기본값은 API/COMMON 및 업무 범위 우선순위로 선택하며, 제약 규칙은 추가 제약을 함께 검사한다. 서로 다른 종류의 지식에 일괄적인 '수동이면 모두 덮어쓰기'를 적용하지 않는다. 단일값 역할의 동순위 충돌이나 양립할 수 없는 제약은 명시적 해소 전까지 적용을 보류한다. 자동 재추출·기본 재생성으로 수동 보정과 검토 이력이 지워지지 않아야 한다.

### 10.4 문서 변경점 표시와 승인 후 교체

문서 변경 시의 덮어쓰기는 사용자 승인한 신규 개정을 현재본으로 바꾸는 것을 뜻한다. 이전 원문·지식·근거·검토 이력은 추적을 위해 보존하고 현재 조회에서 사용하는 활성본만 교체한다.

1. domain_document_id와 내용 해시로 현재 승인본과 신규 파일을 비교한다. 내용 해시와 API/COMMON·API 목록·업무 범위 설정이 모두 같으면 불필요한 재추출·승인 절차를 만들지 않는다. 설정만 달라진 경우에도 차이를 표시하고 승인받는다.
2. 변경 파일을 PENDING_REVIEW 개정으로 저장하고 현재 승인본을 유지한다. 신규 개정의 지식·근거는 비활성 후보로 준비하며 현재 유효 규칙에 섞지 않는다. 변경 없는 지식이 기존 knowledge_id를 공유하면 기존 VERIFIED 상태를 후보 상태로 낮추지 않고 신규 개정 근거만 승인 대기로 둔다.
3. 원문 줄 단위 추가·수정·삭제와 지식 단위 추가·수정·삭제를 변경안으로 보여준다. 대상 API/COMMON, 업무 범위, 기본값·규칙, 근거 및 기존 전문에 대한 영향도 포함한다. 수정 항목 대응이 모호하면 임의로 병합하지 않고 추가/삭제 후보와 모호성을 표시한다.
4. 사용자가 내용을 검토하고 승인/반려한다. 승인할 변경안은 추출·검증을 완료해야 하며 실패 청크·미해결 충돌이 있는 변경안을 조용히 부분 반영하지 않는다. 사용자가 내용을 보정하면 변경안을 다시 검증해 승인한다.
5. 승인 시 비교 기준의 현재본 해시와 적용 설정이 아직 같은지 확인한 뒤 하나의 트랜잭션으로 현재본 포인터·설정·활성 근거·채택 지식을 신규 개정으로 전환한다. 신규 개정이 기존 내용을 대체하고 삭제된 항목도 반영한다. 승인자·시각·사유·변경안 ID를 기록한다.
6. 이전 문서에서만 유래한 삭제/교체 지식은 현재 적용에서 제외한다. 다른 활성 문서의 근거와 독립적인 수동 보정은 보존한다. 새 규칙과 보정이 충돌하면 명시적 검토 대상으로 남긴다.
7. 반려·보류·추출 실패 시 기존 승인본과 유효 지식을 유지한다. 다른 승인으로 현재본이 바뀌면 오래된 변경안은 그대로 적용하지 않고 새 현재본과 차이를 다시 계산한다.

최초 문서 등록도 사용자 검토·승인 후 활성화한다. 문서 변경 승인에는 해당 변경안의 지식 채택을 포함할 수 있어, 동일 내용을 항목별로 다시 승인하도록 강제하지 않는다. 이 절의 PENDING_REVIEW/APPROVED/REJECTED는 문서 개정·변경안 상태이며 10.2의 지식 상태와 구분한다.

## 11. SQLite 및 산출물 설계

저장 DB는 기존 권장안대로 `output/parameter_kb.db`로 분리한다. 원문·근거·수동 보정·검토 이력·사용량/시간 기록은 보존하고 초기 구현에는 자동 삭제를 두지 않는다.

| 테이블 | 키/주요 컬럼 | 역할 |
| --- | --- | --- |
| `parameter_kb` | PK `(document_id, api_id, parameter_path)`, `base_json`, `canonical_hash`, `active`, 생성/수정 시각 | Canonical 기반 기본 정의 |
| `parameter_usage` | 동일 복합키, 조회·선택·성공·실패 수 | 재생성과 독립된 사용 통계 |
| `domain_document` | PK `(domain_document_id, content_hash)`, version, title, path, 적용 범위, revision_status, active | 승인 대기/현재/이전 문서 개정 |
| `document_current` | PK domain_document_id, current_hash, 승인자/시각 | 현재 승인본 포인터 |
| `document_change_set` | change_set_id, 문서 ID, base_hash, new_hash, 이전/신규 설정 JSON, 원문/지식 diff JSON, 영향·검증 결과, status | 변경점 표시와 사용자 승인 단위 |
| `domain_chunk` | PK `chunk_id`, 문서 복합키, 원문, 줄/offset 범위 | 인용 검증 기준 |
| `parameter_knowledge` | PK `knowledge_id`, kb_scope, kind, entry_method, kind_origin, source, payload JSON, concept_refs/search_text, scope JSON, status, confidence, supersedes_id | API/COMMON 지식·적용 범위·수동 보정 |
| `knowledge_api` | PK `(knowledge_id, document_id, api_id)` | API 등록 시 명시된 대상 API 보존. COMMON은 행 없음 |
| `knowledge_target` | PK `(knowledge_id, document_id, api_id, parameter_path, role)` | API 규칙의 정확한 다중 필드 연결. COMMON은 행 없음 |
| `knowledge_evidence` | PK `evidence_id`, knowledge_id, evidence_type, evidence JSON, nullable chunk_id/run_id, active | 문서 인용 또는 사용자 진술·작성 이력 |
| `kb_review` | review_id, nullable knowledge_id/change_set_id, 이전/이후 상태, reviewer, reason, 시각 | 지식 또는 문서 변경안의 검토 이력 |
| `kb_run` | run_id, 설정/프롬프트/모델 버전, 사용량·시간 요약, 처리 상태·오류 | 실행 결과 및 완료/실패 항목 관리 |

물리 DB는 parameter_kb.db 하나를 사용하고 parameter_knowledge.kb_scope로 API/COMMON을 논리적으로 분리한다. COMMON은 Canonical/knowledge_api/knowledge_target의 외래키를 요구하지 않는다. API 규칙에는 지정 API 목록을 knowledge_api로 보존하고, targets가 미해결이어도 COMMON으로 바뀌지 않게 한다.

parameter_kb.base_json에는 보강 지식을 중복 저장하지 않는다. API 단독 조회는 기본 정의와 연결된 API 지식을 합치고, COMMON 단독 조회는 concept_refs·검색어·업무 범위를 반환한다. 통합 조회는 API 규칙과 COMMON 후보를 구분하고 최종 선택 결과는 별도로 반환한다. 후보는 검토 조회로 분리한다.

scope JSON과 concept_refs도 Pydantic으로 검증한다. COMMON의 개념 참조는 규칙 내 subject/condition/target 역할과 관련 용어를 표현하며 실제 API 경로를 가정하지 않는다. 업무 레지스트리/설정은 별도 입력 계약으로 받고 그래프 자체를 생성하지 않는다. knowledge_evidence는 문서 인용이면 chunk_id와 원문 위치를, 사용자 진술이면 작성자·시각·사유·입력 내용을 요구한다. 직접 입력에 가짜 문서 ID나 추출 run_id를 만들지 않는다.

중복 방지 규칙:

- 기본 레코드: 파라미터 복합키로 upsert
- 지식: kb_scope·kind·정규화된 payload·지정 API/target 복합키 또는 COMMON 개념 참조·업무 범위·입력 경로의 해시로 식별. API/COMMON과 자동/수동 보정을 각각 보존
- 문서 근거: 지식 ID·문서 해시·원문 위치의 해시로 식별
- 사용자 진술: 지식 ID·작성자·정규화한 입력 내용·사유로 중복을 검사. 같은 입력의 반복 제출은 독립 근거 수를 늘리지 않고 필요 시 검토 이력만 추가
- API 매칭 전 후보는 실행별 임시 결과로 보관하고 매칭 후 안정적인 ID로 병합. COMMON은 API 매칭 없이 개념 참조로 ID 확정
- 같은 문서·해시·kb_scope·지정 API 목록/업무 범위·프롬프트/schema·모델·청크 설정이 같으면 완료 작업을 재사용. Canonical 해시는 API 등록에만 재사용 조건으로 포함
- `force=True`로 재추출할 수 있지만 동일 근거 수와 사용 통계는 중복 증가시키지 않음

문서 변경 검출만으로 이전 개정·근거·지식을 비활성화하지 않는다. 신규 개정과 변경안은 별도 보관하고 10.4의 사용자 승인 트랜잭션에서 현재본을 교체한다. 다른 활성 근거와 독립적인 수동 보정은 유지한다. Canonical 변경은 연결된 API 규칙과 이전 전문의 COMMON 적용 결과를 재검증하며 API 미연결 COMMON 전체를 무효화하지 않는다. 업무 범위 변경도 영향이 표시된 변경안으로 검토한다.

문서 입력의 청크별 추출 결과와 직접 입력 항목은 후보로 트랜잭션 저장한다. 현재본 활성화·기존 항목 대체는 승인 시 별도 트랜잭션으로 처리하며 처리 실패 시 기존 확정 지식을 훼손하지 않는다. 원본/현재본/보정은 별도로 보존한다.

출력 제안:

```text
mini_project_2/
├─ preprocessing.ipynb
├─ parameter_kb_plan.md
├─ domain_docs/                         # 실제 문서가 주어질 때 생성
└─ output/
   ├─ canonical_schema.db              # 기존 입력
   ├─ baseline.db                      # 기존 참조
   ├─ parameter_kb.db
   ├─ parameter_kb/api/{document_id}/{api_id}.json
   ├─ parameter_kb/common/knowledge.json  # API 연결 없는 공통 지식
   └─ parameter_kb_runs/{run_id}/
      ├─ report.json
      ├─ llm_usage.json                 # 호출별 토큰·경과 시간
      ├─ document_diff.json             # 원문·지식 변경점 및 사용자 검토 결과
      └─ unresolved.json
```

결과 제공은 노트북 DataFrame, API/COMMON별 JSON, 조회 함수 세 가지로 확정한다. 표에는 kb_scope·API/경로 또는 COMMON 개념·kind·입력 경로·범위·근거·상태를 표시하고 해당 없는 Canonical 정보는 null로 둔다. 통합 조회는 API 우선 선택과 COMMON 보완/제외/미매칭/충돌의 이유·지식 ID를 반환한다. 문서 갱신 표에는 기존/신규값·추가/수정/삭제·영향·승인 상태를 표시한다. 리포트에는 등록·검토·갱신 통계와 LLM 사용량·시간·오류를 포함한다.

## 12. 노트북 셀 및 구현 순서

| 순서 | 셀/함수 제안 | 결과 |
| --- | --- | --- |
| 1 | 경로·문서/직접 입력·도메인/간선 레지스트리·`KB_CONFIG`, `LLM_CONFIG` | 실행 설정 |
| 2 | 기본 레코드·KIND·수동/추출 입력·API/COMMON·근거·규칙·범위 Pydantic 모델 | 저장 구분별 검증 규격 |
| 3 | DB 초기화·조회·`build_base_parameter_records()` | Canonical 기본 변환 |
| 4 | `initialize_parameter_kb()` 실행 | LLM 없이 기본 KB 확인 |
| 5 | kind·payload·선택적 api_ids·대상 복합키 또는 개념 참조·업무 범위 입력 셀 | LLM 없는 수동 API/COMMON 입력 |
| 6 | `register_manual_knowledge()`, `preview_knowledge_impact()` | 공통 검증을 거친 수동 후보·영향 확인 |
| 7 | `load_domain_document()`, `chunk_domain_document()` | 문서·청크·근거 위치 |
| 8 | `call_structured_llm()`, `LLM_CALL_RECORDS` | 문서 경로의 Responses API 호출·사용량·시간 기록, SDK 기본 재시도·timeout |
| 9 | `extract_domain_knowledge()`, `validate_evidence()` | LLM의 kind 분류와 근거 있는 추출 후보 |
| 10 | `retrieve_parameter_candidates()`, `match_parameter_knowledge()` | API 문서 경로에만 매칭, COMMON 등록은 생략 |
| 11 | `validate_knowledge()`, `merge_knowledge()` | API/COMMON별 검증·중복·충돌 판정 |
| 12 | `save_knowledge_batch()`, `review_parameter_knowledge()` | 공통 후보 저장·사용자 검토·수동 보정 이력 |
| 13 | `enrich_parameter_kb()` 실행 | 문서 보강, 실패 시 이어 실행 |
| 14 | `get_parameter_kb()`, `search_common_knowledge()`, API/COMMON별 export·표·report | 저장 구분별 조회 |
| 15 | `get_effective_parameter_knowledge()` | 후속 전문 구성용 API 우선·COMMON 보완 조회/병합 계약 |
| 16 | `preview_document_update()`, `approve_document_update()`, `reject_document_update()` | 차이 표시·사용자 승인/반려·승인 후 현재본 교체 |

기존 노트북의 스타일에 맞춰 각 class와 def 앞에 한 문장 역할 주석을 작성한다. 강의 노트북을 실행하거나 import하지 않고 `client.responses.create()` 호출 방식을 참고한다.

구현 순서는 기본 KB 생성, API/COMMON 저장 분기·KIND/범위 모델, 수동 등록·사용자 검토, COMMON 문서 추출, API 지정 문서의 매칭, 문서 diff·승인 후 교체, 재실행·충돌·오류 처리, API 우선·COMMON 보완 조회/병합, export 순으로 진행한다. 노트북 실행 시 공통 함수 정의는 실행 셀보다 먼저 배치한다.

## 13. 검증과 완료 기준

### 13.1 LLM 없이 확인할 항목

- 선택된 Canonical 파라미터마다 KB 기본 레코드가 하나 생성된다.
- 이름이 같아도 API·경로가 다르면 구분된다.
- `required=false / requiredDeclared=false`는 `UNSPECIFIED`로 표시된다.
- XML 경로, enum, format, 문자열 코드의 선행 0이 보존된다.
- 기본 생성 재실행 후 도메인 지식·검토 이력·사용 통계가 유지된다.
- 문서에 없는 인용과 API 후보에 없는 경로는 채택되지 않는다. COMMON dependency의 개념 참조는 등록 시, 실제 API 참조는 전문 적용 시 검증한다.
- 중복 청크와 재실행이 지식·근거 수를 부풀리지 않는다.
- 문서 변경 시 원문·지식의 추가/수정/삭제가 표시되고 승인 전에는 기존 현재본·활성 근거가 유지된다.
- 승인 시 신규 개정이 현재본을 대체하며 이전 원문·근거·승인 이력과 독립 수동 보정은 보존된다.
- 반려·검증 실패·현재본 변경으로 오래된 변경안이 된 경우 기존 내용을 잘못 덮어쓰지 않는다.
- 일부 청크 추출 실패가 기존 지식의 삭제로 해석되지 않고, 삭제·수정 항목은 완전한 변경안 검토 후 반영된다.
- 특정 Canonical 변경만으로 무관한 COMMON 원본이 비활성화되지 않는다.
- 사용자 선택 항목이 정해진 kind/rule_type으로 변환되고 LLM이 재분류하지 않는다.
- 기본 생성과 직접 입력이 API 키 없이 실행되며 LLM 호출 수가 0이다.
- 사용자 선택 kind와 payload가 불일치하면 적용하지 않고 입력 오류를 반환한다.
- api_ids 미지정/None이면 COMMON으로 저장하고 Canonical 조회·API 검색·필드 매칭이 발생하지 않는다. Canonical 기본 생성의 canonical_api_ids 미지정은 전체 API 처리로 별도 검증한다.
- api_ids 지정이면 API에 저장하고, 빈 목록·잘못된 타입·존재하지 않는 API는 COMMON 전환 없이 오류 처리한다.
- COMMON은 API·parameter_path 없이 채택할 수 있으며 API 미연결 때문에 UNMATCHED가 되지 않는다.
- API 등록에 정확한 복합키가 없는 동명 필드는 미해결로 남기고, 지정 API의 매칭 실패를 COMMON으로 우회하지 않는다.
- COMMON 등록은 도메인/간선 범위 ID와 개념 참조만 검사하며 API 소속 매핑을 요구하지 않는다. API 지정 시 존재하는 지정 목록과 입력 범위 그대로 소속을 연결한다. 전문 적용에는 문맥·필드 적합성이 필요하다.
- 통합 조회가 API 규칙 유무와 관계없이 관련 COMMON을 검색한다.
- 같은 항목의 API/GLOBAL 기본값이 COMMON/EDGE보다 우선하고, API에 없는 항목은 COMMON으로 보완된다. 각 저장 구분 안에서는 간선 > 도메인 > 전역을 따른다.
- COMMON의 추가 제약은 함께 확인하고 API 제약과 충돌하면 적용 충돌로 반환한다. 동순위 충돌도 자동 교체하지 않는다.
- COMMON을 전문에 적용할 때 타입·필수 조건·enum·다중 참조를 검증하고, 판정 결과가 원본 COMMON 상태를 오염시키지 않는다.
- 직접 입력의 작성자·시각·사유, 문서 입력의 인용·위치가 서로 다른 근거 모델로 보존된다.
- 수동 입력의 명시적 채택·이전값 대체 이력이 남고, 자동 재생성으로 보정이 사라지지 않는다.
- .md/.txt만 지원하고, 같은 문서 해시는 중복 갱신을 만들지 않는다.
- 수동/LLM 지식 모두 사용자 검토 전에는 유효 규칙으로 사용되지 않는다.
- 지정 API 또는 문맥·개념으로 후보 목록을 좁힌 후 그 안에서만 Top-K가 선택되는지 확인한다.

### 13.2 LLM 통합 확인

실제 도메인 문서가 주어지면 원문으로 정답표를 소량 작성한다. 별칭·값 변환·조건부 필수·의존성·매칭 불가·상충 문장을 포함한다. 실제 정책과 구분되는 합성 fixture는 별도 테스트 데이터로만 사용할 수 있다.

품질 기준은 기존 권장안대로 실제 문서 표본을 사람이 대조하는 방식으로 확정한다. kind 분류·API 필드 검색·최종 매칭·COMMON 관련성을 각각 기록하며, 표본의 채택 항목은 원문 근거와 검토 이력이 모두 있어야 한다. 표본에서 드러난 오분류·잘못된 참조·조건/단위 누락은 보정 또는 보류한 뒤 완료로 판단한다. 실제 측정 없이 정확도 수치를 목표 달성으로 기재하지 않는다.

- 추출 규칙의 조건·예외·단위가 원문과 일치하는지 확인한다.
- LLM의 kind 및 alias_type/mapping_type/rule_type 분류를 정답표와 비교한다. KIND 분류 정확도와 파라미터 매칭 정확도는 분리 평가한다.
- 같은 내용을 수동 입력과 문서 추출로 넣었을 때 같은 kind별 payload 규격을 통과하며 API/COMMON과 출처·채택 상태가 각각 구분되는지 확인한다.
- Parameter KB와 무관한 API 설명·상태 지식이 다른 저장 대상으로 라우팅되지 않는지 확인한다.
- API 지정 문서의 정답 필드 Top-K 포함 여부와 최종 매칭 정확도를 분리 평가한다. COMMON 등록은 추출 호출만 발생하고 API 매칭 호출이 없는지 확인한다.
- 후속 조회에서는 관련 COMMON의 검색 적합성, 선택 API 필드와의 매칭, API 우선 선택·COMMON 보완 결과를 표본으로 대조한다.
- 관련 지식이 없는 청크가 빈 결과를 반환하는지 확인한다.
- 동일 이름의 여러 후보, NONE/AMBIGUOUS 사례를 확인한다.
- mock 응답과 예외로 refusal·incomplete·timeout·SDK 재시도 후 최종 호출 실패·형식 오류 시 저장 및 재개 동작을 확인한다.
- 호출 성공·실패 시 경과 시간이 기록되고, 응답에 usage가 있는 경우 토큰이 집계되는지 확인한다. 재시도 횟수를 제어하는 별도 루프가 없는지도 확인한다.
- 최초 실호출은 작은 문서와 소수 API로 제한해 사용량 및 결과를 검토한다.

완료 기준은 기본 KB 생성, 두 입력 경로의 KIND 결정, API/COMMON 분기·검증·사용자 검토, API 우선·COMMON 보완 조회, 변경점 표시·승인 후 현재본 교체, 충돌/이력 보존, 멱등 저장, 표·JSON·조회 함수 및 리포트가 모두 가능한 상태다. 실제 전문 생성·업무 API 호출은 후속 범위다. 실제 도메인 문서가 없으면 기본 생성·수동 등록·mock 검증까지만 완료로 보고하며 정책 결정이 미확정인 것으로 취급하지 않는다.

## 14. 확정된 구현 기준

사용자 답변과 '그 외 목록은 권장방식 적용' 지시에 따라 기존 추가 확인/결정 목록은 모두 확정 사항으로 전환했다. 아래 항목은 사용자 재결정이 필요한 대기 목록이 아니라 구현·검증 기준이다.

| 항목 | 확정 내용 | 반영 위치 |
| --- | --- | --- |
| 도메인 파일 | UTF-8 md/txt만 지원 | 2.3, 4.2 |
| API/COMMON·범위 | api_ids 지정 API, 미지정 COMMON. COMMON도 도메인 범위 허용 | 4.1~4.3, 5.4 |
| 범위 연결 | COMMON은 ID/개념만 검증, API는 지정 목록과 범위를 소속으로 연결 | 4.2, 5.4, 10.1 |
| COMMON 참조 | 요건·문맥에 필요한 규칙만 전문에 매칭, API 우선·COMMON 보완 | 5.5 |
| 문서 갱신 | 원문·지식 diff 표시 후 사용자 승인 시 현재본 대체. 승인 전 기존본 유지 | 10.4, 11 |
| 필수 여부 | UNSPECIFIED 보존, 업무상 조건부 필수는 RULE로 보강 | 5.1 |
| LLM·timeout | 강의의 환경변수/default model, responses.create, 60초 초기값·SDK 기본 재시도 | 9 |
| 지식 채택 | 수동/LLM 결과 모두 사용자 검토·명시적 승인/반려 | 4.4, 10.2 |
| 수동 보정 | 원본 보존, 별도 보정·대체 참조·사유·검토 이력 기록 | 10.3 |
| 규칙 표현 | 제한된 연산자·구조, AND/OR 깊이 2, 미지원 내용 보류 | 5.2 |
| 검색 | 지정 목록 또는 문맥 필터로 좁힌 후 로컬 Top-K, 초기 K=10 | 5.5, 8.2 |
| 값 출처 | 기본값·우선순위 저장/조회, 실제 값 생성·바인딩은 후속 | 5.3~5.5 |
| 저장·보존 | parameter_kb.db 분리, 원문·근거·보정·검토·사용량/시간 보존 | 11 |
| 결과 제공 | 노트북 표 + API/COMMON JSON + 조회 함수, 판정 이유 포함 | 11~12 |
| 품질 확인 | 실제 문서 표본을 사람이 대조, 잘못된 후보는 수정/보류 | 13 |

실제 파일 경로·내용, 범위 ID, API 목록, 환경변수 값은 실행 시 제공하는 데이터다. 실제 파일이 아직 준비되지 않은 경우에도 위 구현 기준은 확정된 상태로 유지한다.

## 15. 체크리스트와의 대응

| 기존 체크리스트 | 이 계획에서의 대응 |
| --- | --- |
| 파라미터 타입·필수값 추출 | 기존 Canonical 추출 결과 재사용 및 미명시 상태 보존 |
| Parameter KB 데이터 모델 | 기본 레코드, API/COMMON 구분, 수동 선택/LLM 판단 KIND, 개념/필드 참조·근거·범위·상태·검토 이력 |
| Parameter KB 값 출처 정의 | 사용자/문서 출처, API 우선·COMMON 보완, 기본값 업무 범위·판정 이유 |
| Baseline과 API Metadata 연결 | document_id/api_id 기준 조회 계약만 마련, Metadata 구현과 통합은 별도 |
| Response Outputs 추출 | 이번 범위 밖 |
| 응답값→요청값 연결 후보 생성 | PREVIOUS_RESPONSE 유형만 정의, 실제 후보 생성은 후속 |

이 단계의 결과는 api_ids 지정 규칙과 API 미연결 COMMON 규칙을 분리 보존하고, 전문 구성 시 API 규칙을 우선 참조하면서 관련 COMMON으로 보완할 수 있는 Parameter KB다. 두 입력 경로의 KIND·근거·업무 범위·채택·수동 보정 이력을 함께 추적한다.
