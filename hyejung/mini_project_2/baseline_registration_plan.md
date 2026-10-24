# Baseline Request 등록 및 검증 작업계획서

## 1. 목적

Canonical Schema가 저장된 뒤 request XML body를 API별 Baseline으로 등록하고, 해당 API의 XML 구조와 Canonical Schema가 일치하는지 검증한다.

이 문서는 hyejung/mini_project_2/preprocessing.ipynb의 2번 프로세스 구현 계획이다.

참고 문서:

- [Canonical Schema 및 Baseline 기획서](https://app.notion.com/p/UI-3f1467dd6f4e80db8677e6a7b4cefce3)
- [Hmall multiItem Swagger 문서](https://developers.hmall.com/document?id=5f205b21-baa0-44a6-a1ac-39c4d9395d38&product_api_name=undefined#/PDBItemReg/multiItem)

## 2. 확정 요구사항

- Baseline 입력은 request XML body만 받는다.
- document_id와 api_id를 입력해 Canonical Schema를 조회한다.
- API별 Baseline은 하나만 유지하며 버전 관리는 하지 않는다.
- Baseline 저장용 SQLite DB를 별도로 관리한다.
- Dataset은 XML id attribute로 식별한다.
- Dataset id는 원본 Swagger의 id.example에서 괄호 앞 ds... 문자열만 사용한다.
- null, 빈 문자열, 공백 문자열만 빈 값으로 취급한다.
- XML 구조, 필드 존재 여부, 타입, enum, attribute, unknown field를 검증한다.
- 타입 검증은 string과 숫자 계열(integer, number)에 한정한다.
- 검증 결과는 필드별 표 또는 pandas.DataFrame으로 표시한다.
- required=true 필드가 비어 있어도 다른 오류와 분리해 REQUIRED_EMPTY로 표시한다.
- 검증 오류가 없는 경우 Baseline을 저장한다.
- required 빈 값만 있는 경우 PASS_WITH_REQUIRED_EMPTY 상태로 저장할 수 있다.

## 3. 전체 흐름

~~~text
document_id + api_id 입력
        ↓
canonical_schema.db에서 API 조회
        ↓
request XML body 입력
        ↓
XML 문법 및 root 검증
        ↓
Dataset id 정규화 및 매칭
        ↓
xmlPath 기반 필드 추출
        ↓
구조/필드/타입/enum/attribute/unknown field 검증
        ↓
필드별 DataFrame 표시
        ↓
오류가 없으면 baseline.db upsert
~~~

## 4. 입력 인터페이스

노트북에서 다음 함수를 제공한다.

~~~python
register_and_validate_baseline(
    document_id: str,
    api_id: str,
    baseline_xml: str,
)
~~~

입력 처리 규칙:

1. document_id와 api_id가 비어 있으면 실행하지 않는다.
2. canonical_schema.db에서 복합키로 Canonical JSON을 조회한다.
3. API가 없으면 Baseline을 저장하지 않고 오류를 표시한다.
4. baseline_xml이 비어 있으면 실행하지 않는다.
5. XML body만 받으므로 HTTP header, query, path 값은 입력 대상에서 제외한다.

## 5. Baseline SQLite 설계

파일:

~~~text
output/baseline.db
~~~

테이블:

~~~sql
CREATE TABLE IF NOT EXISTS api_baseline (
    document_id TEXT NOT NULL,
    api_id TEXT NOT NULL,
    baseline_xml TEXT NOT NULL,
    content_type TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    validation_result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (document_id, api_id)
);
~~~

저장 규칙:

- baseline_xml에 입력한 XML 원문을 저장한다.
- content_type은 Canonical Schema의 request content type인 application/xml을 저장한다.
- validation_result_json에 전체 요약과 필드별 결과를 JSON으로 저장한다.
- 같은 document_id와 api_id가 있으면 새 버전을 만들지 않고 upsert한다.
- XML 구조, 타입, enum, attribute, unknown field 오류가 있으면 저장하지 않는다.
- required 빈 값만 있는 경우 PASS_WITH_REQUIRED_EMPTY로 저장한다.

## 6. Dataset id 정규화 및 매칭

### 6.1 정규화 규칙

원본 Swagger example에 설명이 포함되어도 괄호 앞 문자열만 Dataset id로 사용한다.

~~~text
입력: dsItemHdmallImgUrl(백화점 상품 등록시에만 입력)
사용할 id: dsItemHdmallImgUrl
~~~

- 괄호가 없으면 전체 example 값을 사용한다.
- 앞뒤 공백은 제거한다.
- XML의 id attribute와 대소문자를 구분해 완전 일치 비교한다.
- 문자열 "null"은 id 공백으로 취급하지 않는다.

### 6.2 매칭 예시

~~~text
Canonical xmlPath:
 /Root/Dataset[@id="dsItem"]/rows/row/slitmCd

Baseline XML:
 <Root>
   <Dataset id="dsItem">
     <rows>
       <row>
         <slitmCd>2012251415</slitmCd>
       </row>
     </rows>
   </Dataset>
 </Root>
~~~

Dataset id가 다르거나 id attribute가 없으면 XML_STRUCTURE_ERROR 또는 XML_ATTRIBUTE_ERROR로 처리한다.

## 7. XML 검증 규칙

### 7.1 XML 문법 및 구조

다음 항목을 순서대로 검증한다.

1. XML parser로 문법을 확인한다.
2. Canonical root xmlName과 실제 root name을 비교한다.
3. Dataset xmlName과 id attribute 존재 여부를 확인한다.
4. Dataset id가 expected id와 일치하는지 확인한다.
5. rows, row 같은 XML wrapper 계층을 확인한다.
6. Canonical Parameter의 xmlPath로 실제 element 또는 attribute를 찾는다.
7. xmlAttribute=true이면 attribute로 존재하는지 확인한다.
8. xmlAttribute=false이면 element로 존재하는지 확인한다.

### 7.2 필드 존재

- Canonical Schema에 정의된 필드가 XML에 있으면 값을 추출한다.
- required 필드가 없으면 MISSING_FIELD다.
- optional 필드가 없으면 OPTIONAL_MISSING으로 표시할 수 있다.
- required 필드가 존재하지만 null, 빈 문자열, 공백이면 REQUIRED_EMPTY다.
- XML element의 text가 없는 경우도 빈 값으로 처리한다.

### 7.3 빈 값

빈 값은 다음 세 가지로 한정한다.

- 파싱 결과가 null
- 빈 문자열
- 공백만 포함한 문자열

문자열 "null"은 일반 문자열 값이다.

### 7.4 타입

| Canonical type | 검증 방식 |
| --- | --- |
| string | XML text를 문자열로 읽는다. |
| integer | 숫자로 변환 가능하고 소수점이 없는지 확인한다. |
| number | 정수 또는 실수로 변환 가능한지 확인한다. |
| boolean, date 등 | 이번 단계에서는 타입 검증을 생략하고 TYPE_CHECK_SKIPPED를 표시한다. |

타입 오류는 TYPE_ERROR로 처리한다.

### 7.5 enum

- Canonical Schema의 enum이 null이면 검사하지 않는다.
- enum 목록이 있으면 실제 값이 목록에 포함되는지 확인한다.
- 목록에 없으면 ENUM_INVALID다.

### 7.6 attribute

- Canonical xmlAttribute=true인데 XML attribute가 없으면 XML_ATTRIBUTE_ERROR다.
- Canonical xmlAttribute=false인 필드가 attribute로만 존재하면 XML_ATTRIBUTE_ERROR다.
- Dataset 식별용 id attribute는 Dataset 매칭 단계에서 별도로 확인한다.

### 7.7 unknown field

- Canonical Schema에 없는 XML leaf element를 탐지한다.
- Canonical Schema에 없는 XML attribute를 탐지한다.
- Root, Dataset, rows, row 등 known wrapper는 unknown field에서 제외한다.
- unknown field는 UNKNOWN_FIELD 오류로 처리하고 Baseline 저장을 차단한다.

## 8. 검증 상태

필드별 status:

~~~text
VALID
REQUIRED_EMPTY
MISSING_FIELD
OPTIONAL_MISSING
XML_STRUCTURE_ERROR
XML_ATTRIBUTE_ERROR
TYPE_ERROR
ENUM_INVALID
UNKNOWN_FIELD
TYPE_CHECK_SKIPPED
~~~

전체 validation_status:

- PASS: 오류가 없고 required 빈 값도 없음
- PASS_WITH_REQUIRED_EMPTY: 오류는 없지만 required 빈 값이 있음
- FAIL: 구조, 필드, 타입, enum, attribute, unknown field 오류가 있음

REQUIRED_EMPTY는 사용자 확인용 상태이며, 단독으로는 FAIL로 처리하지 않는다.

## 9. DataFrame 출력

검증이 끝나면 필드별 결과를 DataFrame으로 출력한다.

| 컬럼 | 설명 |
| --- | --- |
| path | Canonical 논리 경로 |
| xmlPath | XML 실제 경로 |
| name | 필드명 |
| xmlName | XML 요소 또는 attribute 이름 |
| expected_type | string 또는 숫자 계열 |
| required | 필수 여부 |
| expected_value | enum 등 기대값 |
| actual_value | XML에서 추출한 값 |
| xmlAttribute | attribute 여부 |
| status | 필드별 결과 |
| message | 상세 설명 |

전체 요약 예시:

~~~json
{
  "document_id": "hmall-openapi-v1",
  "api_id": "multiItem",
  "validation_status": "PASS_WITH_REQUIRED_EMPTY",
  "total_fields": 286,
  "valid_count": 280,
  "required_empty_count": 6,
  "error_count": 0,
  "unknown_field_count": 0
}
~~~

## 10. 노트북 셀 구성

2번 프로세스는 다음 셀로 구성한다.

1. Baseline DB 경로와 모델 설정
2. Canonical Schema SQLite 조회 함수
3. Dataset id 정규화 함수
4. XML parser 및 namespace/name helper
5. xmlPath 기반 element/attribute 탐색 함수
6. 구조 및 필드 존재 검증 함수
7. string/number 타입 검증 함수
8. enum, attribute, unknown field 검증 함수
9. 필드별 DataFrame 생성 함수
10. Baseline SQLite upsert 함수
11. document_id, api_id, XML body 입력 실행 셀

새로 추가하는 모든 class와 def 앞에 한 문장 주석을 작성한다.

## 11. 완료 기준

- document_id와 api_id로 Canonical Schema를 조회한다.
- 잘못된 API 식별자는 저장 없이 오류를 표시한다.
- 유효한 XML body를 파싱한다.
- root, Dataset, rows, row 구조를 검증한다.
- Dataset id를 괄호 앞 문자열로 정규화해 매칭한다.
- xmlPath와 xmlAttribute를 기준으로 값을 추출한다.
- string, integer, number 타입을 검증한다.
- enum이 있는 필드를 검증한다.
- required 빈 값을 REQUIRED_EMPTY로 표시한다.
- unknown element와 attribute를 탐지한다.
- 오류가 없으면 필드별 DataFrame을 표시한다.
- 오류가 없으면 baseline.db에 upsert한다.
- required 빈 값만 있으면 PASS_WITH_REQUIRED_EMPTY로 저장한다.
- 동일 API 재등록 시 Baseline 1건을 교체한다.
- baseline.db에는 버전별 row를 만들지 않는다.

## 12. 제외 범위

- 실제 Hmall API 호출
- HTTP header, query, path 입력 및 검증
- Baseline 버전 이력
- response field 검증
- Scenario IR outputs, bindings, assertions
- boolean, date, datetime의 정밀 타입 검증
- 업무 규칙, dependency, value mapping 검증
- LLM 기반 Parameter KB 생성

## 13. 예상 이슈 및 대응

| 이슈 | 대응 |
| --- | --- |
| example에 설명이 붙어 있음 | 괄호 앞 ds 문자열만 사용한다. |
| Dataset id가 다름 | 구조 오류로 처리하고 저장하지 않는다. |
| XML field가 없음 | required는 MISSING_FIELD, optional은 OPTIONAL_MISSING으로 표시한다. |
| required 값이 비어 있음 | REQUIRED_EMPTY로 표시하되 단독으로는 실패 처리하지 않는다. |
| type이 boolean 등임 | TYPE_CHECK_SKIPPED로 표시한다. |
| unknown field가 있음 | UNKNOWN_FIELD로 처리하고 저장을 차단한다. |
| baseline.db가 잠겨 있음 | SQLite 연결을 닫고 timeout과 오류 정보를 표시한다. |

## 14. 기대 산출물

~~~text
hyejung/mini_project_2/
├─ preprocessing.ipynb
├─ baseline_registration_plan.md
└─ output/
   └─ baseline.db
~~~

Baseline 검증이 완료되면 API별 기준 request XML과 필드별 검증 결과를 보유하게 되며, 이후 자연어 시나리오에서 Baseline 값을 patch하는 단계의 입력으로 사용할 수 있다.

