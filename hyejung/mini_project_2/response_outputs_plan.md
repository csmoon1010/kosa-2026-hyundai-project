# Response Outputs 추출·SQLite 저장 작업계획서

작성일: 2026-10-27  
구현 대상: `hyejung/mini_project_2/preprocessing.ipynb`에 추가할 `## 4. Response Outputs`

## 1. 목적과 요구사항

Swagger의 API별 응답 스키마에서 후속 API 연결에 사용할 Output 정의를 추출하고 SQLite에 저장한다. 저장 대상은 응답 필드의 정의이며, 실제 API 호출로 얻은 응답값은 아니다.

근거 문서: [메인프로젝트 아키텍쳐/UI (혜정)](https://app.notion.com/p/UI-3f1467dd6f4e80db8677e6a7b4cefce3)의 **1️⃣ API 정의서/스킬 업로드 및 툴 등록 → 6. Response Outputs**.

기획서의 필드는 `api_id`, `name`, `response_path`, `type`, `description`, `enabled`, `source_type`, `status_code`다. 응답 정의를 JSON 형태로 보존하고 사용자가 후속 Step 연결에 사용할 주요 Output을 선택할 수 있어야 한다.

사용자 확인에 따라 XPath 추가 저장, `200_fail` 구분 저장, 성공 응답 필드만 최초 `enabled=true`로 생성하는 정책을 적용한다. `200_fail` 등 실패 응답과 성공 여부 미확정 응답은 `enabled=false`로 저장한다. DB·함수 구성은 이를 구현하기 위한 설계안이다. 추가 확인 질문은 이 문서에 포함하지 않는다.

## 2. 현재 상태와 연결 지점

| 항목 | 확인 내용 | 구현 방향 |
| --- | --- | --- |
| 노트북 구성 | 1번 Canonical Schema, 2번 Baseline, 3번 ParameterKB까지 구현됨 | 마지막에 독립적인 4번 절 추가 |
| Canonical 범위 | `CanonicalApi.parameters`는 요청 파라미터만 저장 | 응답은 원본 Swagger에서 직접 추출 |
| 원본 | `output/swagger_raw.json`, OpenAPI `3.0.1` | 저장된 원본으로 오프라인 처리 |
| API 식별 | operationId, 없으면 method·endpoint 기반 fallback | 기존 `build_canonical_api()`의 ID 규칙 유지 |
| 응답 정의 수 | API 43개, `200` 43개, `200_fail` 41개 | 총 84개 정의를 각각 보존 |
| 미디어 타입 | 위 84개 모두 `application/xml` | XML 실제 요소·속성 경로 보존 |
| 비표준 키 | `200_fail` 설명에 실제 HTTP Status Code는 200이라고 명시 | 원본 응답 키와 HTTP 상태 분리 |
| XML 구조 | Response2XML, Dataset, rows, row, Dataset/@id | schema 속성 경로와 XML 경로 구분 |
| 설명형 example | 판매상품코드(예:2211221122) 등 | 원본 example과 추출 설명을 구분 |
| 저장 방식 | Canonical·Baseline·Parameter KB가 별도 SQLite 파일 사용 | Response Outputs도 별도 DB 구성 |

수치는 2026-10-27에 저장된 원본 파일에서 확인한 스냅샷이며 실행 시 재집계한다. 최신 서버 문서를 다시 조회한 수치로 간주하지 않는다.

재사용 후보는 `PROJECT_DIR`, `OUTPUT_DIR`, `RAW_PATH`, `DOCUMENT_ID`, `DB_PATH`, `now_iso()`, `model_to_dict()`, `append_path()`, `resolve_json_pointer()`, `extract_description()` 및 XML 메타데이터 함수다.

기존 `walk_schema()`는 요청 위치를 전제로 하며 순환 참조·배열 처리도 보완해야 하므로 응답용 순회 함수를 별도로 작성한다. 기존 요청 Canonical 모델에 응답 필드를 섞지 않는다.

## 3. 범위와 확정 정책

구현할 기능:

1. 선택 문서·API의 모든 responses와 미디어 타입 순회.
2. 내부 $ref, 중첩 object, array, XML 메타데이터에서 Output 추출.
3. 응답 정의 JSON과 Output별 레코드의 SQLite 저장.
4. 노트북 입력 셀을 통한 주요 Output 사용 설정·조회.
5. 재추출 시 사용자 설정 보존과 변경·삭제 필드 처리.
6. API별 추출·누락·경고·실패 보고.

적용 정책:

- 입력은 저장된 `RAW_PATH`를 우선한다. 메모리의 `raw_swagger` 직접 전달도 지원하되 한 실행에서는 한 원본만 사용한다.
- 대상은 Canonical DB에 등록된 해당 문서의 전체 API다. api_ids를 지정하면 해당 범위만 처리한다.
- 신규 Output은 `response_kind=SUCCESS`일 때만 `enabled=true`로 자동 활성화한다. `200_fail`을 포함한 FAILURE 및 UNKNOWN 응답의 필드는 `enabled=false`로 저장한다. 사용자는 성공 응답의 불필요한 필드를 비활성화할 수 있으며, 재추출에서도 해당 설정을 보존한다. 실패·미확정 응답은 수동 설정으로도 활성화할 수 없다.
- 성공 응답과 `200_fail`은 response_key와 response_kind로 구분하여 모두 저장한다. 전체 목록 조회에서는 두 종류를 함께 확인하며, 기본 후속 연결 조회는 enabled인 성공 응답 필드만 반환한다. 실패 응답은 enabled=false 상태로 보존하며, 비활성 필드를 포함하는 전체 조회에서 응답 키·응답 구분을 지정하여 확인한다.
- XML의 실제 추출 위치인 XPath를 저장하고, schema의 JSONPath 형태 논리 경로도 schema_path에 함께 보존한다. XML의 response_path는 XPath, JSON의 response_path는 응답 body를 루트 $로 하는 JSONPath이며 path_type으로 구분한다.

실제 API 호출, 실응답 파싱·값 추출, 다음 API 입력 바인딩, Scenario IR 생성, 웹 UI, LLM·임베딩 기반 주요 필드 추론은 후속 범위다. 경로의 실행 가능성은 최소 샘플로 검증한다.

## 4. 처리 흐름과 실행 의존성

~~~text
저장된 Swagger + Canonical DB의 대상 API 목록
  → 문서·api_id·method·endpoint 대응 검증
  → operation.responses 순회
  → 원본 응답 키·HTTP 상태·응답 구분 저장
  → Response Object 참조 해석 → 모든 content 순회
  → schema 참조 해석·필드 순회
  → 경로·타입·설명·XML 메타데이터 생성
  → 모델·중복 검증 → 신규 Output의 response_kind에 따라 enabled 설정(SUCCESS만 true) → API 단위 SQLite transaction
  → 전체 Output·경고 표시 → 필요한 경우 사용자 비활성화·이름 보정
  → 활성 Output 조회 / API별 JSON export
~~~

4번 절은 1번의 공통 정의와 Canonical DB만 필요로 한다. Baseline, Parameter KB, OpenAI 설정, Chroma 초기화에 의존하지 않는다. 오프라인 실행 시 1번 정의 셀만 실행하고 Swagger 재조회 실행 셀을 건너뛸 수 있도록 안내한다.

Canonical DB의 source_hash와 원본 해시가 다르거나 API ID·method·endpoint가 대응하지 않으면 저장을 중단한다. 해시는 기존 `persist_results()`의 JSON 직렬화 규칙과 동일하게 계산한다. 원본 불일치 오류에는 Canonical과 원본을 같은 스냅샷으로 갱신하도록 안내한다.

## 5. 추출·정규화 규칙

### 5.1 응답 정의

- 식별자는 `(document_id, api_id, response_key, content_type)`다.
- response_key는 200, 200_fail, default, 2XX 등 원본 문자열 그대로 저장한다.
- status_code는 문자열 또는 null이다. 정확한 숫자 키는 그대로, 현재 Hmall의 200_fail은 문서 설명에 근거하여 "200"으로 정규화한다. 다른 비표준 키에서 숫자를 임의로 잘라내지 않는다.
- response_kind는 SUCCESS / FAILURE / UNKNOWN이다. 현재 문서의 200_fail은 FAILURE다. default·의미 불명 키는 UNKNOWN으로 둔다. HTTP 200만으로 업무 성공을 확정하지 않는다.
- Response Object 자체와 content의 schema에 있는 $ref를 모두 처리한다.
- 빈 content·schema 없는 응답·204도 Output 0개인 응답 정의로 보존한다. 빈 content의 저장 키는 `content_type=''`로 통일하고 사유를 기록한다.

### 5.2 필드·타입·설명

- object의 속성을 재귀 순회하여 기본적으로 leaf 필드를 Output으로 만든다. properties가 비어 있는 object는 구조만 보존하고 활성화 가능한 leaf를 만들지 않는다.
- array 자체와 items의 leaf를 구분한다. JSON 반복 경로는 `$.items[*].id` 형식으로 표현하며 루트 배열·원시값 배열·items의 $ref도 처리한다.
- type, format, enum, nullable, required 선언, 원본 example은 있을 때 보존한다. 타입을 알 수 없으면 unknown과 경고를 남기고 review_required=true로 설정한다. 최초 enabled는 응답 구분에 따라 설정하되(SUCCESS만 true), 검토 전 후속 연결 조회에서 제외한다.
- description을 우선하고 없으면 기존 `extract_description()`의 example 접두부 추출을 적용한다. 설명형 example을 실제 응답값으로 생성하지 않는다.
- 특수문자 필드명은 `append_path()`의 인용 규칙을 따른다.
- 반복 경로의 type은 개별 필드 타입이다. 복수 값 여부는 cardinality로 구분하며 첫 값 선택·반복 실행은 후속 바인딩 정책으로 남긴다.

### 5.3 XML과 JSON 경로

| 필드 | JSON 응답 | XML 응답 |
| --- | --- | --- |
| schema_path | schema 속성 기준 논리 경로 | data1/data2 등 schema property 기준 논리 경로 |
| response_path | 실제 body 기준 JSONPath | 실제 요소·속성 기준 XPath |
| path_type | JSONPATH | XPATH |
| XML 메타데이터 | null / false | 이름·속성·namespace·wrapped 등 |
| cardinality | schema에 따라 ONE / MANY | 반복성이 불명확하면 UNKNOWN |

현재 multiItem 상품코드의 저장 예시:

~~~json
{
  "document_id": "hmall-openapi-v1",
  "api_id": "multiItem",
  "response_key": "200",
  "status_code": "200",
  "response_kind": "SUCCESS",
  "content_type": "application/xml",
  "name": "slitmCd",
  "schema_path": "$.data1.data2.data3.slitmCd",
  "response_path": "/Response2XML/Dataset[@id=\"dsItem\"]/rows/row/slitmCd",
  "path_type": "XPATH",
  "type": "string",
  "description": "판매상품코드",
  "cardinality": "UNKNOWN",
  "enabled": true,
  "source_type": "SWAGGER"
}
~~~

Dataset/@id는 Dataset을 구분하는 선택자에 반영하며 속성 필드 자체는 /@id로 표현한다. 일반적인 XML→dict 변환만으로 $.data1... 경로에서 값을 조회할 수 있다고 가정하지 않는다.

현재 문서는 row를 object로 정의한 경우가 있어 이름만으로 단일값·배열을 확정하지 않는다. namespace·xml.wrapped 등은 보존하고 지원 가능한 경로를 생성하되 해석 불가능한 부분은 경고·검토 대상으로 남긴다.

사용자 확인에 따라 기획서의 JSONPath 예시를 확장하여 schema의 논리 경로와 실제 XML XPath를 함께 저장한다. 향후 모든 응답을 공통 JSON으로 정규화한다면 변환 규칙을 먼저 정의한 뒤 response_path 계약을 조정한다.

### 5.4 참조·복합 스키마·중복

- 내부 JSON Pointer는 기존 resolver를 재사용한다. 재귀 순회에서는 현재 조상 참조 집합과 최대 깊이를 전달해 순환을 차단하며 다른 경로의 동일 schema 재사용은 허용한다.
- 미해결·외부 참조는 위치와 원본 $ref를 남기고 해당 부분을 검토 대상으로 처리한다. 외부 문서를 자동 다운로드하지 않는다.
- allOf는 속성·required를 모으되 같은 필드의 타입·제약 충돌 시 경고하고 review_required=true로 설정하여 검토 전 후속 연결 조회에서 제외한다. 저장된 추출 필드의 최초 enabled는 SUCCESS일 때만 true이며 FAILURE/UNKNOWN은 false다.
- oneOf·anyOf는 원본을 보존한다. 분기 구분이 구현되지 않은 부분을 단일 타입으로 합치지 않으며 미지원 경고를 남긴다.
- 같은 leaf 이름이 여러 경로에 존재하면 경로 기반 접미사 등 결정적인 규칙으로 name을 구분한다. 중복 필드를 덮어쓰지 않는다.
- name은 응답 정의 안에서 유일해야 한다. 여러 응답 정의를 Scenario에 함께 선택할 때는 응답 키·미디어를 지정하고 이름 충돌을 검증한다.

## 6. SQLite 설계

경로: `OUTPUT_DIR / 'response_outputs.db'`. JSON은 SQLite TEXT에 한글을 유지하여 직렬화한다. 기존 DB·요청 Canonical 구조는 변경하지 않는다.

### api_response_schema: 응답 정의 단위

| 컬럼 | 내용 |
| --- | --- |
| document_id, api_id, response_key, content_type | 복합 PK |
| status_code, response_kind | 정규화 HTTP 상태·응답 구분 |
| method, endpoint, description | API 연결 정보·응답 설명 |
| source_type, source_url, source_hash | SWAGGER 출처·원본 추적 |
| schema_json | 선택 schema와 필요한 내부 참조 정의·원본 포인터 |
| warnings_json, extraction_status | 경고, COMPLETE / PARTIAL / NO_SCHEMA / FAILED |
| is_active, created_at, updated_at | 원본 존재 여부·저장 시각 |

schema_json에는 관련 내부 참조 정의도 넣어 선택 schema만 저장했을 때 참조가 끊기는 문제를 방지한다. 전체 원본은 기존 swagger_raw.json을 사용한다.

### response_output: 필드 단위

| 컬럼 | 내용 |
| --- | --- |
| document_id, api_id, response_key, content_type, schema_path | 복합 PK; 앞 4개는 응답 정의 테이블 FK |
| generated_name, name_override | 자동 이름·선택 사용자 이름; 조회 name은 override 우선 |
| response_path, path_type | 실제 필드 위치·경로 해석 방식 |
| type, format, description | 타입·설명 |
| metadata_json | enum, nullable, required, example, XML 정보, cardinality, source pointer/ref |
| enabled | INTEGER 0/1, DEFAULT 0; 신규 SUCCESS 필드만 1로 저장하며 FAILURE/UNKNOWN은 0 유지 |
| definition_hash, review_required, is_active | 구조 변경 검토·삭제 감지 |
| created_at, updated_at | 생성·갱신 시각 |

연결마다 `PRAGMA foreign_keys=ON`을 적용한다. 모델·중복 검사 후 API 단위 transaction으로 저장하며 사용자 입력은 SQL placeholder로 바인딩한다.

## 7. 재실행·변경·부분 실패 정책

- 동일 원본은 upsert하여 행이 증가하지 않게 한다. 신규 SUCCESS 필드만 enabled=true로 생성하고 FAILURE/UNKNOWN 필드는 false로 저장한다. 기존 SUCCESS 필드의 enabled·name_override를 보존하여 사용자가 비활성화한 필드를 재추출만으로 다시 활성화하지 않는다. 응답 구분이 FAILURE/UNKNOWN으로 변경되면 enabled=false로 갱신한다.
- 경로·타입·배열 여부 등 추출 계약 변경 시 review_required=true로 둔다. 사용자 설정은 보존하되 후속 연결 조회에서 제외하고 명시적 재확인으로 해제한다.
- 정상 순회가 완료된 대상 범위에서 사라진 필드·응답 정의는 is_active=false로 표시한다. 물리 삭제하지 않는다.
- 일부 API만 처리하면 대상 밖 API는 변경하지 않는다. 파싱 실패·미해결 참조 때문에 보이지 않는 기존 필드도 삭제로 간주하지 않는다.
- 실패 API는 rollback하여 기존 데이터를 유지하고 실패를 보고한다. PARTIAL API는 성공 필드만 갱신하며 미해결 범위의 기존 필드는 보존하고 검토 대상으로 제외한다.
- 기본 후속 연결 조회 조건은 `response_kind=SUCCESS AND enabled=true AND is_active=true AND review_required=false`와 상위 응답 정의의 활성 여부다. FAILURE/UNKNOWN 필드는 비활성 필드를 포함하는 전체 조회에서 명시적으로 확인한다.
- 실패 실행은 별도 리포트에 남긴다. 기존 정상 데이터를 실패 상태로 덮어쓰지 않는다.

## 8. 함수와 노트북 구성

로직은 기존 스타일에 맞춰 노트북 정의 셀에 작성한다. 아래 함수명은 구현 제안이다.

| 함수 | 책임 |
| --- | --- |
| load_response_source(raw_path, document_id, api_ids=None) | 원본·해시·Canonical 대상 검증 |
| extract_api_responses(document, canonical_api) | 응답 키·미디어별 정의·Output 모델 생성 |
| walk_response_schema(...) | 경로·타입·XML 추출, 참조·배열·재귀 보호 |
| initialize_response_outputs(document_id, api_ids=None) | 추출·검증·SQLite 동기화·보고 |
| configure_response_output(output_key, enabled, name=None, confirm_review=False) | 복합키로 사용 설정·이름·변경 재확인; FAILURE/UNKNOWN의 enabled=true 요청은 검증 오류 |
| get_response_outputs(document_id, api_id, ...) | 응답 키·미디어·활성 여부·실패 포함별 조회 |
| export_response_outputs(document_id, api_ids=None) | 현재 DB 정의·설정의 API별 JSON 출력 |

추가할 셀 순서:

1. **4.1 설정·모델·공통 함수**: DB 경로, 응답 정의/Output 모델, resolver·경로 처리.
2. **4.2 Swagger 응답 추출·저장**: 대상 문서·API 입력, 실행·요약.
3. **4.3 응답 정의·필드 확인**: 전체 목록, 원본 키·미디어·경로·경고.
4. **4.4 Output 사용 설정 변경(선택 실행)**: 자동 활성화된 필드 중 불필요한 항목을 복합키로 비활성화하거나 이름을 보정.
5. **4.5 활성 Output 조회·JSON export**: 후속 연결용 정의 조회·선택 export.

추출·저장 셀은 신규 SUCCESS 필드만 enabled=true로 생성하고 FAILURE/UNKNOWN 필드는 enabled=false로 저장한다. 이후 수동 설정 셀은 선택 실행으로 분리하며 예시 설정은 기본 비실행 스위치를 사용하여 기존 사용자 선택을 바꾸지 않게 한다. export는 선택 기능이며 조회 기준·생성 시점을 함께 기록한다.

## 9. 단계별 작업과 완료 기준

| 순서 | 작업 | 완료 기준 |
| --- | --- | --- |
| 1 | API·원본 연결 및 모델 정의 | API ID·method·endpoint 대응과 원본 불일치 감지 |
| 2 | 응답 정의·필드 추출 | 현재 84개 정의와 200_fail 구분, XPath·논리 경로·타입·출처 보존 |
| 3 | SQLite 초기화·동기화 | 신규 SUCCESS만 enabled=true, FAILURE/UNKNOWN은 false, 복합키·FK 유효, 재실행 중복 없음·사용자 설정 유지 |
| 4 | 노트북 4번 절 추가 | Baseline/KB·네트워크·API 키 없이 저장된 원본으로 실행 |
| 5 | 경계 사례·재실행 검증 | 실패 응답·배열·참조·변경·부분 실패 검증 통과 |
| 6 | 결과·사용법 정리 | 활성 JSON, 경고·누락 보고 및 경로 계약 확인 |

## 10. 검증 계획

원본 파일 기반 확인과 작은 합성 schema의 경계 사례를 검증한다. 전체 노트북 실행은 1번 네트워크 조회와 3번 외부 호출·지식 등록을 유발할 수 있으므로 공통 정의와 새 4번 셀만 격리하여 확인한다.

| 항목 | 기대 결과 |
| --- | --- |
| 원본 범위 | API 43개, 200 43개, 200_fail 41개와 정의 수 일치 |
| multiItem 상품코드 | 5.3 예시의 schema_path·XPath 정확한 대응, 최초 enabled=true |
| XML 최소 샘플 | XPath로 상품코드 조회; 여러 row면 여러 값 반환, 첫 값 자동 선택 없음 |
| selectItem 실패 응답 | 200_fail 별도 정의, HTTP 200, FAILURE, /error/code 등의 경로, 추출 필드 enabled=false |
| JSON·배열·특수문자 | 샘플 JSONPath 조회, 루트·중첩·원시값 배열 처리 |
| 참조·순환 | 정상 참조 재사용, 순환·미해결은 무한 재귀 없이 경고·검토 제외 |
| 복합 스키마 | allOf 충돌·oneOf/anyOf 미지원이 조용히 합쳐지지 않음 |
| 빈 schema·다중 미디어 | Output 0건 사유·모든 미디어별 정의 보존 |
| 이름 중복 | 같은 leaf 이름의 다른 경로 보존 및 이름 구분 |
| 초기 활성화·조회 | 신규 SUCCESS 필드만 enabled=true, 200_fail 등 FAILURE/UNKNOWN은 false; 기본 후속 연결 조회는 SUCCESS만 반환 |
| 활성화 조건 검증 | FAILURE/UNKNOWN에 대한 수동 enabled=true 요청은 오류; HTTP 200인 200_fail도 활성화하지 않음 |
| 재실행·설정 | 중복 없음; 기존 SUCCESS의 사용자 enabled=false·이름 유지, 신규 SUCCESS만 true, FAILURE/UNKNOWN으로 변경 시 false |
| 변경·부분 실행·실패 | 변경 검토 제외, 삭제 비활성화, 대상 밖 유지, 실패로 기존 필드 삭제 없음 |
| 원본 불일치 | Canonical 해시·API 대응 불일치 시 저장 전 오류 |

필드 수는 첫 추출 결과에서 집계하여 API·응답 키·미디어별로 기록하고 예상 leaf 수를 임의로 고정하지 않는다. 리포트에는 정의 수, 생성/갱신/비활성/검토 필요 Output 수, schema 없는 응답 수, API별 실패·경고를 포함한다.

## 11. 산출물

- preprocessing.ipynb의 `## 4. Response Outputs` 정의·실행·조회 셀.
- `output/response_outputs.db`: 응답 정의·사용자 설정.
- `output/response_outputs_report.json`: 통계·경고·실패.
- `output/response_outputs/<document_id>/<api_id>.json`: 선택 export.
- 추출·동기화 경계 사례 검증 코드.

## 12. 구현 결과 (2026-10-27)

위 계획에 따라 노트북 4번 절의 정의·추출·저장·설정·조회·선택 export 셀을 구현하고 실제 DB 및 추출 리포트를 생성했다. 기존 1~3번 셀의 내용은 보존했다.

| 항목 | 실제 결과 |
| --- | --- |
| API / 응답 정의 | 43개 / 84개 |
| 추출 Output | 1,053개 |
| 성공 응답 Output | 930개, enabled=true |
| 실패 응답 Output | 123개, enabled=false |
| 처리 실패 / 검토 필요 | 0개 / 0개 |
| 경고 | selectItem의 하위 필드가 없는 object 정의 12곳 |

원본의 비표준 대문자 DATE 타입은 string / format=date로 정규화하며 metadata.raw_type에 원본을 보존한다.

검증 결과:

- `test_response_outputs.py` 25개 통과: 원본 추출, 4번 독립 실행, XPath·JSONPath, 실패 응답 활성화 차단, 참조·배열·부분 실패·재실행·export.
- 기존 Parameter KB 오프라인 검증 25개 통과. 기존 검증이 새 4번 실행 셀까지 수행하지 않도록 3번 절의 종료 경계를 지정했다.
- 기존 `test_notebook_stage3_with_existing_canonical`은 사용자가 켠 3번의 외부 호출 스위치로 인해 OpenAI 인증정보를 요구한다. 전체 검증 최초 실행에서 이 항목은 인증정보 부족으로 실패했으며, 이후 오프라인 검증에서는 이 항목을 제외했다. 기존 실행 스위치는 변경하지 않았다.
- SQLite integrity_check 및 foreign_key_check 통과.

사용 방법:

1. 기존 1번 설정 셀로 PROJECT_DIR·DOCUMENT_ID를 정의한다. 저장된 원본을 사용하므로 Swagger 조회 실행 셀과 2~3번 실행은 필요 없다.
2. 4.1 정의 셀부터 4.2 추출·저장, 4.3 확인, 4.5 활성 조회를 실행한다.
3. 4.4 사용 설정 변경과 4.5 JSON export는 각각 실행 스위치를 켰을 때만 수행한다.
4. 전체 필드는 `response_outputs.get_response_outputs(DOCUMENT_ID, api_id, include_inactive=True, include_failures=True)`로 조회한다. 기본 조회는 활성 SUCCESS 필드만 반환한다.

실제 저장 경로는 `output/response_outputs.db`, `output/response_outputs_report.json`이다. API별 JSON export는 검증용 임시 경로에서 확인했으며 실제 프로젝트에서는 선택 실행으로 유지했다.
