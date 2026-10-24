# Swagger 조회 API 기반 Canonical Schema 생성 작업계획서

## 1. 목적

hyejung/mini_project_2/preprocessing.ipynb에서 Hmall Swagger 조회 API의 OpenAPI JSON을 읽고, API 선택·파라미터 검색·Baseline Request 생성·Parameter KB 연계에 사용할 수 있는 표준 JSON(Canonical Schema)으로 변환한다.

Canonical Schema는 원본 Swagger의 구조를 그대로 저장하는 문서가 아니라, API마다 달라지는 표현을 공통 필드와 공통 파라미터 경로로 정규화한 실행용 메타데이터다. 원본 JSON과 변환 경고를 함께 보존해 추후 오류를 추적할 수 있게 한다.

## 2. 입력 및 확인된 Swagger 구조

- 조회 API: Hmall Swagger 조회 URL
- 참고 설계: 메인프로젝트 아키텍쳐/UI (혜정)
- 구현 대상: hyejung/mini_project_2/preprocessing.ipynb
- 원본 입력: Hmall Swagger 조회 API 응답 JSON
- 출력 예시: output/swagger_raw.json, output/canonical_schema/

Swagger에서 확인된 주요 특징:

- OpenAPI 3.x 문서다.
- info.title, info.version, paths, components.schemas를 사용한다.
- paths 아래 다수의 operation과 operationId, summary, description이 존재한다.
- 공통 header가 required: "true"처럼 문자열로 표현될 수 있다.
- 요청 미디어 타입은 주로 application/xml이다.
- requestBody schema가 components.schemas의 $ref를 사용한다.
- XML 구조를 표현하기 위해 Root, Dataset, rows, row 등의 중첩 object와 xml.name을 사용한다.
- Dataset id는 XML attribute로 표현된다.
- 일부 example은 업무 설명과 예시값을 함께 포함한다.

## 3. 작업 범위

### 3.1 MVP 범위

1. Swagger 조회 URL에서 원본 JSON을 가져온다.
2. OpenAPI 문서의 모든 paths와 HTTP operation을 순회한다.
3. operation 단위 Canonical Schema를 생성한다.
4. header, path, query, cookie, request body를 parameters 배열로 평탄화한다.
5. $ref를 해석하고 중첩 object/array를 재귀적으로 펼친다.
6. XML name, XML attribute, XML 실제 경로를 보존한다.
7. 변환 결과의 구조와 핵심 제약을 Pydantic으로 검증한다.
8. document_id + api_id 단위의 API별 JSON 파일을 저장한다.
9. API별 JSON 전문을 SQLite에 저장한다.
10. 원본 문서, canonical 결과, 변환 경고와 통계를 보존한다.

### 3.2 이번 단계에서 제외하는 항목

- 실제 Hmall API 호출 및 인증정보 저장
- 업무 문서 기반 aliases, value_mappings, rules, dependencies 추출
- LLM 기반 설명 보정이나 자연어 별칭 생성
- 응답 필드의 평탄화
- Scenario IR용 outputs 정의
- 응답 필드의 Parameter KB 또는 RAG 적재
- Baseline 등록 및 검증 프로세스

## 4. Canonical Schema

### 4.1 API 단위 구조

~~~json
{
  "documentId": "hmall-openapi-v1",
  "documentTitle": "HSHOP OPEN API Swagger",
  "apiId": "selectItem",
  "method": "POST",
  "endpoint": "/pd/pdb/selectItem.do",
  "summary": "상품 상세 조회",
  "description": "상품 상세 조회",
  "tags": ["PDBItemReg"],
  "contentType": "application/xml",
  "requestBodyRequired": true,
  "parameters": [],
  "source": {
    "documentUrl": "https://developers.hmall.com/main/swagger/...",
    "openapiVersion": "3.0.1",
    "documentVersion": "v1"
  },
  "warnings": []
}
~~~

### 4.2 Parameter 구조

~~~json
{
  "path": "$.body.data3.data1.data1.slitmCd",
  "location": "body",
  "name": "slitmCd",
  "type": "string",
  "required": false,
  "requiredDeclared": false,
  "description": "판매상품코드",
  "format": null,
  "enum": null,
  "example": "판매상품코드(타입:string, 예:2012251415)",
  "sourceRef": "#/components/schemas/multiItemRequest",
  "xmlName": "slitmCd",
  "xmlPath": "/Root/Dataset[@id=\"dsItem\"]/rows/row/slitmCd",
  "xmlAttribute": false
}
~~~

### 4.3 필드 정규화 규칙

| Canonical 필드 | 생성 규칙 |
| --- | --- |
| documentId | Swagger 문서를 식별하는 안정적인 문서 ID |
| documentTitle | Swagger info.title |
| apiId | operationId 우선. 없으면 method와 endpoint 기반 fallback ID 생성 |
| method | HTTP method를 대문자로 변환 |
| endpoint | Swagger paths의 endpoint를 그대로 보존 |
| summary/description | operation 값을 사용하고 없으면 null |
| contentType | requestBody의 media type |
| location | header, path, query, cookie, body 중 하나 |
| path | JSON 구조 기반 논리 경로. body는 $.body..., header는 $.headers... |
| xmlName | 명시적인 xml.name을 우선하고 없으면 property 이름 |
| xmlPath | XML 실제 경로. Root, Dataset, rows, row 등의 wrapper를 포함 |
| xmlAttribute | xml.attribute가 true이면 true |
| type | string, integer, number, boolean, object, array로 정규화 |
| format | int64, date, date-time 등 원본 format 보존 |
| required | 원본 required를 boolean으로 변환 |
| requiredDeclared | 원본에 required 선언이 있었는지 기록 |
| description | 명시적 description을 우선하고, 없으면 example 기반 설명을 보조적으로 추출 |
| enum | 원본 enum이 있을 때 배열로 기록 |
| example | 원본 example을 값 예시로 보존 |
| sourceRef | 원본 components schema의 JSON Pointer |
| documentId/documentTitle | API별 JSON 전문에도 반복 저장 |

### 4.4 XML body 처리 원칙

- path는 논리적인 property 경로로 유지한다.
- xmlPath는 실제 XML 요소와 attribute 위치를 표현한다.
- XML xml.name이 없으면 property 이름을 xmlName으로 사용한다.
- xml.attribute=true인 필드는 XML attribute로 구분한다.
- Dataset처럼 반복되는 XML 요소는 id attribute selector를 포함할 수 있다.
- example은 경로를 만들기 위한 값이 아니라 필드 값 예시로만 사용한다.
- data1, data2, data3처럼 의미가 약한 wrapper도 원본 계층을 보존한다.
- XML 경로 생성 시 괄호가 포함된 Dataset id example은 괄호 앞의 ds 문자열을 사용한다.
- 응답 schema와 응답 필드는 읽거나 평탄화하지 않는다.

## 5. 노트북 구현 계획

### Step 1. 실행 환경 및 설정

- Swagger URL, timeout, user-agent, 출력 디렉터리, document_id를 상수로 둔다.
- document_id는 Swagger 문서 단위의 안정적인 값으로 설정한다.
- documentTitle은 Swagger info.title에서 읽는다.
- Pydantic을 모델 검증에 사용한다.
- HTTP 호출은 표준 라이브러리 또는 httpx를 사용한다.
- 인증정보는 코드와 출력에 하드코딩하지 않는다.
- 조회 API 호출 제한이 없으므로 별도 rate limit이나 pagination은 적용하지 않는다.
- 네트워크 장애에 대비한 timeout과 오류 처리는 유지한다.

### Step 2. 원본 Swagger 조회 및 메타데이터

- HTTP status, Content-Type, 응답 본문 크기를 확인한다.
- JSON object 또는 JSON 문자열로 한 번 더 감싸진 응답을 처리한다.
- swagger_raw.json에 원본을 저장한다.
- info.title, info.version, openapi, servers를 문서 메타데이터로 만든다.
- source hash를 계산해 원본 변경 여부를 확인한다.
- JSON 파싱 실패 시 오류와 응답 메타데이터를 report에 기록한다.

### Step 3. OpenAPI 기본 검증

- openapi가 3.x인지 확인한다.
- info, paths, components.schemas의 존재 여부를 확인한다.
- paths가 비어 있으면 실패 처리한다.
- operationId 중복, 지원하지 않는 method, 잘못된 $ref를 사전 점검한다.
- 원본 문서는 변경하지 않고 warning에 기록한다.

### Step 4. $ref resolver와 schema walker

다음 함수 단위로 분리한다.

- resolve_json_pointer: 로컬 JSON Pointer를 해석한다.
- resolve_schema: $ref와 inline schema를 병합한다.
- normalize_type: Swagger 타입을 Canonical 타입으로 정규화한다.
- extract_description: description과 example에서 설명을 추출한다.
- get_xml_metadata: xml.name과 xml.attribute를 가져온다.
- get_xml_segment: XML 요소와 Dataset selector를 생성한다.
- append_xml_path: 현재 XML 경로에 요소 또는 attribute를 추가한다.
- walk_schema: object, array, primitive를 재귀 탐색해 parameter를 생성한다.
- coerce_bool: boolean과 문자열 boolean을 안정적으로 변환한다.

모든 class와 def 앞에는 역할을 한 문장으로 설명하는 주석을 작성한다.

### Step 5. operation 단위 변환

각 path, method, operation에 대해 다음 순서로 처리한다.

1. operation identity와 기본 설명을 만든다.
2. parameters 배열의 header/path/query/cookie 항목을 변환한다.
3. requestBody의 media type과 schema를 선택한다.
4. request body schema를 $.body 기준으로 재귀 순회한다.
5. logical path와 XML path를 함께 생성한다.
6. operation별 warning을 API 결과에 추가한다.

### Step 6. Pydantic 검증 및 품질 통계

- CanonicalParameter, CanonicalApi, CanonicalDocument 모델을 정의한다.
- apiId와 endpoint, method 조합의 중복을 검사한다.
- 모든 parameter path가 $.로 시작하는지 검사한다.
- location과 path prefix가 일치하는지 검사한다.
- required는 boolean인지 검사한다.
- type은 허용된 canonical type인지 검사한다.
- unresolved ref, unknown type, malformed schema를 warning으로 집계한다.
- API 수, parameter 수, warning 수를 canonical_schema_report.json에 기록한다.

### Step 7. API별 JSON 및 SQLite 저장

API별 JSON 위치:

~~~text
output/canonical_schema/{document_id}/{api_id}.json
~~~

Canonical Schema SQLite 테이블:

~~~sql
CREATE TABLE IF NOT EXISTS api_canonical_schema (
    document_id TEXT NOT NULL,
    api_id TEXT NOT NULL,
    document_title TEXT NOT NULL,
    method TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    canonical_json TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (document_id, api_id)
);
~~~

저장 규칙:

- canonical_json에 API별 JSON 전문을 UTF-8 JSON 문자열로 저장한다.
- 동일한 document_id와 api_id가 있으면 upsert한다.
- source_hash로 원본 Swagger 변경 여부를 확인한다.
- document_id는 JSON과 SQLite에 모두 저장한다.
- api_id가 없으면 method와 endpoint 기반 fallback ID를 만든다.
- 같은 문서 내 api_id가 중복되면 저장 전에 오류 처리한다.

### Step 8. 결과 확인

권장 산출물:

~~~text
hyejung/mini_project_2/
├─ preprocessing.ipynb
├─ canonical_schema_plan.md
└─ output/
   ├─ swagger_raw.json
   ├─ canonical_schema.db
   ├─ canonical_schema_report.json
   └─ canonical_schema/
      └─ hmall-openapi-v1/
         ├─ selectItem.json
         ├─ multiItem.json
         └─ ...
~~~

샘플 확인 API:

- selectItem: 조회 API, header와 중첩 XML body
- multiItem: 상품 등록 API, 큰 중첩 request schema
- selectCnryCodeList: request schema가 없거나 비어 있는 예외 케이스
- selectOshpDtlList: 날짜와 문자열 타입이 섞인 케이스

## 6. 검증 및 완료 기준

### 기능 검증

- Swagger 조회 응답을 실행해 API별 JSON을 생성한다.
- 모든 operation에 documentId, documentTitle, apiId, method, endpoint, parameters가 존재한다.
- 공통 header가 header parameter로 추출된다.
- $ref가 해석되고 body leaf property가 $.body 경로로 생성된다.
- application/xml contentType이 보존된다.
- required: "true"가 boolean true로 정규화된다.
- 비표준 타입이 canonical type과 warning으로 변환된다.
- xmlName이 없는 body field는 property 이름으로 보완된다.
- xmlPath가 Root, Dataset, rows, row와 leaf field를 반영한다.
- XML attribute 필드가 xmlAttribute=true로 저장된다.
- API별 JSON 파일이 저장된다.
- SQLite에 (document_id, api_id) 복합키로 JSON 전문이 저장된다.
- 재실행 시 동일한 key로 upsert된다.

### 품질 검증

- Pydantic validation error가 0건이다.
- unresolved ref가 없거나 report에 원본 ref와 경로가 남는다.
- 원본 JSON과 canonical 결과가 분리 저장된다.
- JSON의 documentId와 SQLite의 document_id가 일치한다.
- 응답 필드와 outputs가 결과에 포함되지 않는다.

## 7. 예상 이슈 및 대응

| 이슈 | 대응 |
| --- | --- |
| 조회 API에 인증 또는 특정 header가 필요함 | 인증정보를 환경변수 또는 secret reference로 주입한다. |
| Swagger가 JSON이 아닌 HTML로 반환됨 | Content-Type과 응답 시작 부분을 확인하고 명확한 오류를 남긴다. |
| $ref 대상이 없음 | 해당 branch를 제한적으로 변환하고 warning을 기록한다. |
| required 정보가 없음 | required=false와 requiredDeclared=false로 구분한다. |
| XML wrapper가 너무 깊음 | canonical에는 원본 경로를 보존하고 검색용 의미 부여는 후속 단계로 둔다. |
| media type이 여러 개임 | MVP에서는 primary media type을 사용하고 warning을 기록한다. |
| SQLite 파일이 잠겨 있음 | 연결을 닫고 timeout을 설정하며 저장 실패 원인을 출력한다. |

## 8. 완료 후 기대 결과

노트북 실행 후 Swagger 원본을 보존하면서 document_id와 api_id 단위의 API별 Canonical Schema JSON 및 SQLite 레코드가 생성된다. Canonical Schema는 기본 API 정보, 요청 파라미터, JSON 논리 경로, XML 실제 경로를 포함하며, 이후 Baseline Request와 API Metadata, Tool Registry, Parameter KB를 연결하는 기준 데이터로 사용된다.

