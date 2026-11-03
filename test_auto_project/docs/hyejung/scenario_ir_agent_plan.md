# 백엔드 고정 계획 기반 Scenario IR 생성 에이전트 작업계획서

작성일: 2026-10-31
수정일: 2026-11-01

## 적용할 설계: ParameterKB 기본 조회 + 상황별 추가 조회

이 설계는 소스에 반영했다. 모델은 KB 기본 조회와 Baseline·Response Outputs 조건부 조회의 3개 도구를 사용하며, 네 도구 전체 호출을 요구하던 완료 조건을 제거했다. 현재 검증 범위와 재시도 정책은 함께 관리하는 `scenario_ir_validation_retry_plan.md`를 기준으로 한다.

- LLM에는 `get_parameter_knowledge`(기본), `get_baseline_request`(조건부), `get_response_outputs`(조건부)의 **3개 도구**를 제공한다. `get_request_schema`는 모델 도구에서 제외한다.
- ParameterKB는 자연어를 파라미터 경로·값으로 연결하는 기본 자료다. 파라미터의 `identity`, `knowledge`, **`schema`**, `provenance`를 함께 전달한다.
- LLM은 조건의 매핑 후보를 `StepMappingResult`로 작성한다. 후보가 Baseline과 같은지 다른지는 백엔드가 결정한다. LLM에 Baseline을 항상 조회하거나 변경 없는 항목을 미리 제거하도록 요구하지 않는다.
- 백엔드는 Canonical로 KB의 기술 정보를 보완하고 IR의 method·endpoint·content type 등을 구성한다. Baseline은 매 STEP의 후보 비교에 사용하되, 이 내부 사용을 LLM의 Baseline 조회로 세지 않는다.
- STEP 완료는 KB와 업무의 조회 결과 의존성을 기준으로 확인한다. 의존성이 있으면 빈 outputs/bindings 또는 일반 unresolved로 응답 조회를 건너뛸 수 없다. 조회 후에도 판단 불가한 관계만 dependency_ids와 구체적 사유를 남겨 미해결 처리한다.
- `client.responses.create()`·Pydantic Structured Outputs·고정 단계·화면 예산 설정·초안 저장·미리보기·실시간 로그·JSONL은 유지한다.
- `validate_mapping`은 모델에 노출하지 않는 백엔드 전용 기능이다. 기본 모드는 비활성화하고, 정지·재시도 적용 모드는 보충 계획서에 정의한 inputs·outputs·bindings 검사만 수행한다. 필수 여부 판단·Assertion 생성·실제 업무 API 실행·사용자 질문은 제외한다.
- 앞서 폐기한 STEP 간 캐시·자료 자동 주입 설계는 이번 계획에 포함하지 않는다.

## 1. 목적과 구현 범위

`prototype/offline-ui.html`의 시나리오 등록 화면에서 의도분석과 API 선택 결과를 불러온 뒤 기존 **승인** 버튼을 누르면, 저장된 통합 승인 JSON을 입력으로 Scenario IR 초안을 생성한다.

이번 구현의 결과는 **IR 초안 파일 저장 + 화면 미리보기**다. 현재 분석 모드에서 assertions는 빈 배열로 두며, 응답 검증 조건을 생성하지 않는다. 실제 업무 API 호출, 최종 상태 확인용 API 단계 추가, 기존 실행용 시나리오 등록은 포함하지 않는다.

출력은 첨부 형식의 시나리오 식별 정보·`sources`·`tasks[].steps[]`·`final_outputs`를 외부 구조로 사용하고, 각 단계에 전체 요청 경로·타입·XML 위치·근거·구조화된 Binding·Assertion을 결합한다. 생성 단계의 `generation`만 기록하며 실행용 `approvals`, `permission`, `execution_policy`, `wait/poll`, 별도 조회 `verify`는 출력에 추가하지 않는다.

에이전트 TOOL은 KB 기본 조회와 Baseline·Response Outputs 조건부 조회의 3개로 구성한다. Canonical과 `validate_mapping`은 모델 도구가 아니라 백엔드에서 처리한다. `request_user_input`은 이번 범위에서 제외한다. 부족한 정보는 `unresolved`로 기록해 미리보기에 표시하며, 생성 도중 사용자에게 질문하거나 답변을 받아 재개하는 흐름은 만들지 않는다.

이 문서는 구현 계획이다. 에이전트·서버·화면 코드는 별도 구현 단계에서 작성한다. 운영·보안 고도화는 이번 작업 범위에 포함하지 않는다. 실행 설정은 화면에서 조정할 기본값과 전달 계약까지만 정의한다.

## 2. 현재 구현과 연결 지점

| 대상 | 현재 역할 | 구현 방향 |
|---|---|---|
| `prototype/offline-ui.html` | 시나리오 등록 화면과 기존 IR 표시 | 생성 설정 영역과 새 IR 초안 미리보기 영역 추가 |
| `prototype/api-selection-import.js` | 의도분석·API 선택 JSON 불러오기, 통합 승인 JSON 저장 | 승인 저장 성공 후 해당 승인 파일로 IR 생성 요청 |
| `src/tap/ui/serve.py` | `/api/approved-selections` 등 로컬 서버 API | 승인본 기반 IR 생성 API 추가 |
| `src/tap/ui/preprocessing.py` | API ID별 파라미터 자료 조회·정규화 | 원본 JSON 조회·API ID 정규화 로직 재사용 |
| `src/tap/ir/build.py` | 상태 그래프와 경로 계산 결과로 기존 IR 생성 | 기존 경로는 유지하고 승인본 기반 초안 모델·생성기를 별도로 추가 |

기존 `/api/plan`은 상태 그래프·목표·경로 탐색을 사용하는 기능이다. 이번 흐름에서는 이 경로로 API를 다시 선택하거나 순서를 다시 계산하지 않는다.

## 3. 입력 데이터

### 3.1 통합 승인 JSON

입력 위치: `prototype/approved/`

기준 예제: `prototype/approved/api-selection-approved-order-shipment.json`

| 필드 | 용도 |
|---|---|
| `original_question` | 원본 요청과 값 추출 근거 |
| `intent_tasks` | 업무 목적·조건·건수·순서 |
| `api_selection_results` | 사용할 API와 각 업무의 처리 단계 |
| `unresolved` | 이전 단계에서 전달된 미해결 항목 |
| `source_files` | 원본 의도분석·API 선택 파일 이름 |

사용할 파일은 현재 화면에서 승인한 뒤 서버가 반환한 **실제 저장 파일 이름**으로 지정한다. 같은 이름의 파일이 있어 서버가 접미사를 붙인 경우에도 반환된 이름을 그대로 사용한다. 폴더의 최신 파일을 임의로 선택하지 않는다.

이미 저장된 승인본으로 다시 생성할 때는 화면에서 승인본 파일을 선택하는 목록을 제공한다. 목록 항목에는 파일 이름과 원본 요청을 표시한다. 이 목록은 기존 두 입력 JSON을 불러오는 기능과 별도로 제공한다.

### 3.2 API별 파라미터 자료

기준 디렉터리: `data/out/parameters/`

| 하위 경로 | 용도 |
|---|---|
| `canonical_schema/` | 백엔드의 KB 기술 정보 보완 및 IR API 기술 정보 구성 |
| `parameter_kb/api/` | LLM 기본 자료: 의미·별칭·기본값·값 매핑·규칙·의존성과 schema |
| `parameter_kb/common/knowledge.json` | 해당 API·파라미터에 적용되는 공통 지식 |
| `response_outputs/` | 응답 필드 경로·타입·참조 가능한 출력 정의 |
| `baseline/` | 요청 구조와 등록값·예시값 구분 |

통합 승인본의 `selected_api_id`는 `hshop-openapi:POST:/...` 형식이다. 파라미터 문서의 `document_id/documentId`와 `api_id/apiId`를 결합해 같은 형식으로 맞춘다. 파일 이름의 해시나 URL 인코딩 문자열로 자료를 연결하지 않는다.

첫 버전의 Baseline 입력은 위 `baseline/` JSON으로 한정한다. 별도 사용자 등록 디렉터리까지 합치는 기존 UI용 로더의 동작은 이번 에이전트 입력에 자동으로 적용하지 않는다. 기존 로더의 정규화 함수를 재사용하되, 에이전트용 자료 조회 범위를 분명하게 구분한다.

### 3.3 요건 검토와 자료 제공 방향

적용 가능하다. 실제 `parameter_kb/api/` 문서는 파라미터별 schema에 type·enum·format·xml_path 등을 이미 가진다. 변경 전 `ParameterTools.read()`는 KB 반환 시 schema를 누락했다. 현재는 identity·knowledge·schema·schema_sources·provenance를 함께 반환하고, 누락된 기술 필드는 Canonical에서 보완한다.

- KB와 Canonical은 `document_id:api_id`와 전체 parameter_path로 연결한다. KB의 schema가 없거나 기술 필드가 빠진 경우에만 백엔드가 Canonical 기술 정보를 보완한다. 의미·별칭·업무 규칙을 Canonical에서 추측해 VERIFIED 지식으로 승격하지 않는다.
- 보완 필드에는 실제 원본의 source_id·source_pointer를 유지한다. KB에서 제공한 기술 정보와 Canonical에서 보완한 정보의 근거를 섞지 않는다. 필수 여부 필드는 자료에 있어도 판단에는 사용하지 않는다.
- KB 파라미터 정의·CANONICAL_DERIVED 설명과 VERIFIED 업무 지식은 구분한다. 추가 업무 규칙·기본값은 검증 상태와 적용 범위를 확인하며, EXAMPLE_ONLY 값은 확정 실행값으로 사용하지 않는다.
- Canonical은 독립 모델 도구로 노출하지 않는다. KB 자료 보완과 백엔드 IR 기술 정보 구성에 사용한다. KB 자체가 없거나 API·경로 대응이 불가능하면 네 도구를 재호출하는 대신 명확한 자료 오류로 처리한다.

## 4. 구성 방식: 백엔드 고정 계획 + 단일 에이전트

### 4.1 기본 원칙

- 백엔드는 승인된 `intent_tasks.sequence`와 `api_selection_results.path_sequence/step`으로 단계·순서·API를 고정한다. LLM 계획자는 두지 않는다.
- LLM은 KB로 현재 조건에 해당하는 입력 매핑 후보만 작성한다. 전체 요청 필드·필수값 누락을 검토하지 않는다.
- Baseline의 기존 설정 자체를 해석해야 하면 LLM이 조건부 조회한다. 백엔드의 기계적인 값 비교를 위해 LLM에게 추가 조회를 요구하지 않는다.
- 응답 출력이 필요하면 LLM이 Response Outputs를 조회한다. 이전 STEP에서 이미 정의된 출력을 그대로 Binding에 사용하는 경우에는 그 구조화된 정의를 사용한다.
- 같은 API를 여러 STEP이 사용해도 단계별 의도·구분값·Binding을 각각 판단한다. STEP마다 대화는 새로 시작하며 이전 결과는 previous_steps로 전달한다.
- 백엔드는 후보와 Baseline을 비교해 replace/unchanged 등을 결정하고, tasks[].steps[]로 IR을 조립한다. 비교 후 이를 확정하기 위한 LLM 재호출은 하지 않는다.

### 4.2 고정 처리 흐름

```text
승인 JSON 저장 → 화면 설정과 실제 승인 파일 이름으로 생성 요청
    → 승인본 정규화 및 고정 STEP 목록 구성
    → STEP별 에이전트 실행
        → ParameterKB 기본 조회 (schema 포함)
        → 사용자 조건의 경로·값·이전 출력 참조에 대한 매핑 후보 작성
        → 기존 기본값·설정 해석이 필요하면 Baseline 추가 조회
        → 신규 응답 필드 정의·확인이 필요하면 Response Outputs 추가 조회
        → StepMappingResult 반환
        → 백엔드 Pydantic 파싱·STEP ID·필요 자료 확보 확인
            → 필요한 조회가 누락되면 구체적인 자료 피드백 후 같은 STEP 진행
            → 부족한 업무 정보는 근거 없는 값 대신 unresolved로 남김
        → 백엔드가 Baseline과 후보를 비교하여 대체 여부·비교 정보를 부여
        → STEP 결과 채택 및 다음 STEP 진행
    → Canonical 기술 정보와 STEP 결과로 IR 초안 조립
    → JSON 저장 → 화면 미리보기
```

Baseline과 Response Outputs는 필요할 때 각각 조회하며 서로 고정된 호출 순서는 없다. 동일 턴에 여러 도구가 요청되면 기존 Runtime처럼 순차 실행하고 결과를 함께 다음 입력으로 전달한다. 실제 업무 API 응답값은 아직 없으므로 Binding에는 값 대신 출력 정의의 참조를 기록한다.

### 4.2.1 후속 업무 조건과 조회 결과 의존성

`ir/dependencies.py`가 승인된 업무 조건과 고정 STEP을 대조해 의존성을 구성한다. 업무·단계·API를 추가하거나 재정렬하지 않으며 LLM 계획자는 사용하지 않는다.

- 모든 고정 STEP과 following_steps 항목에 해당 업무의 `intent_task`를 함께 전달한다. 후속 API의 선택 이유만이 아니라 실제 `intent_task.conditions`를 확인할 수 있다.
- “1번 업무에서 조회한 주문”·“1번 업무의 결과” 같은 명시적 결과 참조를 추출한다. 참조 업무에 STEP이 하나이거나 조회 STEP이 하나로 특정되면 출처를 확정한다. 업무 번호 없는 조회 결과 참조는 앞선 조회 STEP이 하나일 때만 연결한다.
- 출처가 여러 개이거나 없거나 뒤 업무를 가리키면 `status=ambiguous`로 남긴다. 단순한 업무 순서나 “완료 후” 같은 순차 실행 조건만으로 데이터 의존성을 만들지 않는다. 자유로운 자연어 참조를 모두 해석하는 기능은 아니며, 확정하지 못한 출처를 임의로 선택하지 않는다.
- 의존성은 dependency_id·출처 업무/STEP/API·소비 업무·조건·원본 source_pointer·status를 가진다. 생산 STEP에는 `output_consumers`, 소비 STEP에는 `input_dependencies`로 제공한다. 기준 예제에서는 `D-1-to-2`가 1-1에서 2-1/2-2/2-3으로 이어진다.
- 이 값은 결과 배열과 독립적인 완료 조건에 사용한다. IR STEP에도 같은 메타데이터를 보존하고, 명시적으로 확인된 선행 업무는 Binding 미완성 시에도 depends_on에 반영한다.

생산 STEP은 KB 다음에 현재 API의 응답 조회가 필요하다. 소비 STEP은 앞 STEP에 출력이 없으면 출처 API의 응답 조회가 필요하다. 이 경우 `tool_choice`를 get_response_outputs로 지정하고 API 인자도 필요한 출처로 제한한다. 기존 출력이 충분하거나 조회 의존성이 없는 STEP은 기존의 조건부 선택을 유지한다.

### 4.3 강의 하네스 적용

`hyejung/lecture/5. harness_core.ipynb`의 모델 호출 → 도구 호출 → 도구 결과 전달 구조를 사용한다.

| 구성 요소 | 이번 구현에서의 역할 |
|---|---|
| Runtime | `agent/runtime.py`의 `Runtime.run`: 모델 호출 → 도구 결과 전달 → 최종 결과 반환 루프 |
| ToolRegistry | `agent/tool_registry.py`의 `TOOLS`, `ToolRegistry.call_tool`: 기본 KB + 조건부 조회 2개의 스키마·설명·실행 연결·오류 변환 |
| Session | Runtime의 messages에 현재 단계·후속 단계 목적·앞 단계 결과·도구 결과 전달 |
| Trace | Runtime의 usage·trace에 요청 전체의 사용량과 단계별 도구 호출 기록 |
| CONFIG | `agent/config.py`: 숫자 기본값·설정 검증과 프롬프트·오류 문구·모델 연결 옵션 분리 |

고정 계획과 단계별 결과는 대화 밖의 백엔드 상태로 관리한다. 이 부분은 `4. planning.ipynb`의 결과 관리 방식을 참고한다. 앞 단계 출력은 `4-1. dependent_plans.ipynb`처럼 값 대신 명시적인 참조로 연결한다. 멀티에이전트 라우터·핸드오프는 구성하지 않는다.

### 4.4 실제 구현의 파일 경계와 설정 전달

- `src/tap/agent/config.py`: `DEFAULTS`에 숫자 설정 4개를 정의한다. `configuration()`이 화면 설정을 병합·검증하고, `harness_configuration()`이 요청별 서버 CONFIG 사본을 만든다.
- 같은 파일의 `CONFIG`에는 instructions, 모델 환경변수 이름, SDK 재시도 횟수, Pydantic 모델에서 생성한 strict JSON Schema 응답 형식과 errors를 둔다. instructions는 `prompts.py`의 SYSTEM을 사용한다. 하네스 오류 문구와 도구 오류 변환 문구는 CONFIG의 errors에서 관리한다.
- `src/tap/agent/tool_registry.py`: 모델에 노출할 `TOOLS` 정의와 ToolRegistry를 관리한다. `call_tool()`이 실제 ParameterTools에 연결하며, STEP별 자료 제공 결과와 필요한 자료를 관리한다. `finish()`는 Pydantic 파싱과 자료 확보를 처리한다. basic 모드는 기존 단계 식별·의존성 피드백을 유지하고, validated 모드의 매핑 검사는 보충 계획서 범위에 따른다.
- `src/tap/agent/output_models.py`: STEP 결과용 Pydantic 모델을 정의하고 Structured Outputs 스키마를 제공한다.
- `src/tap/agent/parameter_tools.py`: KB의 schema 포함 반환·Canonical 기술 보완·조건부 자료 읽기와 `validate()` 진입점을 담당한다. validated 모드에서만 보충 계획서가 정한 inputs·outputs·bindings 검증을 호출한다. 기본값이나 화면 설정 검증은 여기에 두지 않는다.
- `src/tap/agent/runtime.py`: CONFIG와 레지스트리를 받아 모델 호출, 누적 사용량 확인, 대화·트레이스를 관리한다. 도구 스키마·도구 이름별 분기·변경 가능한 오류 문구를 직접 정의하지 않는다.
- `src/tap/ir/draft_build.py`: `fixed_plan()`과 `generate()`가 고정 계획, 계층형 IR 조립과 저장을 담당한다. STEP 출력 계약은 Pydantic 모델로 표현하고, 백엔드 Baseline 비교 결과를 덧붙여 최종 IR을 조립한다. basic 모드는 검증 호출을 비활성화하고, validated 모드는 `ir/draft_validate.py`를 통해 inputs·outputs·bindings만 저장 전에 재검사한다.

설정 전달은 **화면 generation_config → config.configuration() → Runtime 생성 → harness_configuration()의 요청별 CONFIG 사본** 순서다. 화면에 내려주는 기본값과 생성 결과의 `generation.config`는 숫자 4개만 포함한다. 서버 instructions·errors·모델 옵션은 화면 입력이나 IR의 숫자 설정에 섞지 않는다. CONFIG의 중첩 값도 요청별로 복사해 다른 요청과 공유 변경되지 않도록 한다.

강의의 CONFIG·도구 정의/실행·코어 루프 경계를 적용한다. 강의와 같은 `client.responses.create()` 연결을 사용하고, 이번 범위에서 제외한 Policy 승인 기능은 새로 추가하지 않는다.

### 4.5 강의와 맞춘 Responses API 실행 흐름

- `Runtime.run()`은 강의의 `run()`처럼 입력 목록을 시작하고, `client.responses.create(model, instructions, input, tools, store=False)`를 반복 호출한다. 시스템 지시문은 CONFIG에서 읽어 매 호출의 `instructions`로 전달한다.
- 도구 정의는 강의의 `spec()`처럼 `type/name/description/strict/parameters`를 같은 계층에 두고, 모든 인자를 required로 지정하며 추가 인자를 허용하지 않는다.
- 응답의 `output`에서 `type=function_call` 항목을 모아 순서대로 실행한다. 모델이 한 턴에 여러 도구를 요청할 수 있다. 도구 실행 결과는 요청의 `call_id`를 가진 `function_call_output`으로 다음 입력에 추가한다.
- 다음 호출에는 응답의 전체 output 항목을 보존한다. reasoning 항목도 포함하며, `store=False`에서 필요한 암호화 컨텍스트는 `include=['reasoning.encrypted_content']`로 받는다. STEP 전환 시에는 새 입력 목록을 만들고 앞 STEP 결과는 `previous_steps`로 전달한다.
- 도구 호출이 없으면 `response.output_text`를 `StepMappingResult`로 파싱한다. KB 기본 조회와 필요 자료·현재 STEP ID를 확인하며, 필요한 자료가 빠졌으면 해당 자료만 조회하도록 피드백한다. 조건부 도구를 호출하지 않았다는 이유로 거부하지 않는다.
- `response.status=incomplete`와 `incomplete_details.reason=max_output_tokens`는 출력 한도 오류다. 다른 미완료·실패·거절 응답도 완료 결과로 채택하거나 도구를 실행하지 않고 오류를 기록한다. Chat Completions의 `finish_reason`은 사용하지 않는다.
- 사용량은 Responses의 `input_tokens/output_tokens/total_tokens`로 집계한다. 화면·JSONL에 실제 `instructions/input/tools/text/store/include`와 원본 응답·상태를 기록한다.
- 강의의 CONFIG·ToolRegistry·Runtime·Session·Trace 경계를 유지한다. 실제 화면 진행 로그와 STEP 결과 파싱이 필요하므로 강의 예제의 40줄 제한을 그대로 적용하지 않는다. 예산은 기존처럼 전체 IR 요청에서 공유하고, 조회·실행 권한 관련 제외 범위는 유지한다.
- SDK 요구사항은 `openai>=1.68.2`로 올린다. 설치된 버전이 낮으면 requirements 설치 후 서버를 재시작한다.

## 5. AGENT가 사용하는 TOOL

모델에 제공할 도구는 3개다. 인자는 전체 `selected_api_id` 문자열이며 반환 형식은 `source_id`, `source_file`, `source_pointer`, `data`를 유지한다. 승인본 읽기·Canonical 읽기·Baseline 비교·IR 조립·저장은 백엔드 역할이다.

| 자료·도구 | 제공 방식 | 주요 내용과 조회 목적 |
|---|---|---|
| `get_parameter_knowledge` | 기본 조회 | identity·knowledge·schema·provenance, VERIFIED API·공통 지식. 자연어 조건을 요청 경로·값으로 매핑할 기본 자료 |
| `get_baseline_request` | 조건부 조회 | 현재 기본값·설정·출처·validation_status. 기존 설정을 유지·변경·해석해야 하는 경우 사용 |
| `get_response_outputs` | 조건부 조회 | 활성 성공 응답 필드·경로·타입·행 범위. STEP 연결이나 최종 출력의 신규 응답 필드를 정의할 때 사용 |
| Canonical (`get_request_schema` 모델 도구 제외) | 백엔드 사용 | KB의 기술 필드 보완 및 IR의 API ID·method·endpoint·content type 구성 |
| `validate_mapping` | 백엔드 전용 | 모델 도구로 노출하지 않으며, 적용 모드에서 보충 계획서에 정한 inputs·outputs·bindings 검증에 사용 |

KB의 각 parameters 항목은 `identity`, `knowledge`, `schema`, `provenance`, 원본 `source_pointer`를 포함한다. schema에는 type·enum·format·XML 위치를 보존한다. 현재 도구의 schema 누락을 수정하며, 단순 검색 요약으로 전체 파라미터의 기술 정의를 대체하지 않는다.

첫 LLM 호출은 KB 기본 조회를 요청하도록 도구 선택을 제한한다. 정상 KB 결과를 모델에 전달한 뒤 Baseline·Response Outputs를 필요에 따라 선택할 수 있도록 한다. 기본 조회에 성공한 이후에는 전체 도구를 채우기 위한 호출을 요구하지 않는다. CONFIG에는 이 기본 도구와 자료 부족 피드백 문구를 두고, 숫자 UI 설정 계약은 유지한다.

### 5.1 STEP에 필요한 자료와 완료 조건

| 상황 | 확보해야 할 자료 | 생략 가능한 조회 |
|---|---|---|
| 사용자에게 명시된 값의 요청 경로 매핑 | 현재 API의 KB 및 schema | LLM의 Baseline·Response Outputs |
| 기존 기본값이나 설정의 의미를 해석해 후보 작성 | KB + LLM에 전달된 Baseline 결과 | 응답 출력이 필요 없다면 Response Outputs |
| 현재 STEP에서 후속 STEP·최종 출력용 필드 새로 정의 | KB + 현재 API의 Response Outputs | 기존 설정 해석이 없다면 LLM의 Baseline |
| 앞 STEP의 기존 output을 현재 입력에 Binding | KB + previous_steps의 해당 출력 정의 | 이미 정의된 필드를 재확인하기 위한 Response Outputs |
| 필요한 앞 STEP 출력이 아직 정의되지 않음 | 출처 API의 Response Outputs 확인이 필요 | 현재 API의 무관한 응답 조회 |

- 백엔드가 실제 전달한 도구 결과와 previous_steps의 출력 정의로 자료 확보 상태를 관리한다. 모델이 “조회했다”고 서술하는 것만으로 완료로 세지 않는다.
- KB 기본 조회가 성공하고 현재 STEP ID가 일치해야 한다. JSON·자료 필드의 형식은 Pydantic 모델로 파싱한다.
- outputs를 새로 정의하는 경우 해당 API의 Response Outputs가 모델에 전달되어야 한다. Baseline에서만 알 수 있는 기존 값·설정을 근거로 후보를 작성했다면 그 Baseline 자료가 전달되어야 한다. 필요 여부는 출력·근거의 자료 의존성으로 확인하며 모든 자연어 의미를 판정하는 새 검증기를 추가하지 않는다.
- Binding이 previous_steps의 기존 출력 정의를 사용하면 그 자료로 충분하다. 앞 STEP의 출력이 없으면 승인된 출처 API의 Response Outputs를 먼저 조회한다. 제안된 참조의 response_key·content_type·response_path·path_type·row_scope가 조회 자료와 일치할 때만 백엔드가 필요한 출력 정의를 앞 STEP에 보완한다. 기존 정의와 충돌하거나 확인되지 않은 경로는 보완하지 않으며, 앞 STEP 입력·API·업무 순서는 바꾸지 않는다.
- 기존 값 해석의 필요성은 LLM이 판단하되, 백엔드는 실제 공급하지 않은 Baseline 근거를 사용한 결과에 자료 부족 피드백을 준다. 단순한 값 비교나 변경 여부 확인만을 이유로 Baseline 재호출을 강제하지 않는다.
- 조건부 조회가 불필요하고 outputs·bindings가 비어 있어도 정상 완료할 수 있다. 필수 여부·전체 필드 완성 여부는 완료 조건이 아니다.
- 필요 자료를 아직 조회하지 않은 경우와 실제로 조회했으나 업무 정보가 부족한 경우를 구분한다. 전자는 필요한 조회를 안내하고, 후자는 임의 값 없이 unresolved로 기록해 초안을 계속 작성한다. 자료 파일 누락·손상은 별도 생성 오류로 표시하고 동일 조회를 무한 반복하지 않는다.
- basic 모드는 생산 STEP의 outputs 및 소비 STEP의 Binding 누락에 대해 기존 보완 피드백을 유지한다. 적용 모드에서는 자료 조회 동작은 유지하지만, 의존성 커버 여부와 unresolved.dependency_ids는 보충 계획서의 매핑 검증 범위에서 제외한다.
- 적용 모드에서 validate_mapping은 입력 경로·기술정보·값·근거, 출력 정의·근거, Binding 출처·목적지·타입·행 범위만 검사한다. 전체 IR 조립 검증과 의미상 조건 적합성 판단을 수행하지 않는다.

### 5.2 조건부 호출 예시

1. “협력사 코드 001442를 입력 조건으로 사용”: KB의 venCd 경로·타입을 확인해 fixed 후보 작성. 기존 설정을 해석할 필요가 없으면 LLM은 Baseline을 생략한다. 백엔드가 나중에 기존 값과 비교한다.
2. “기존 조회 기간은 유지하고 특정 설정만 변경”: 기존 값이 무엇인지 해석해야 하는 항목에 Baseline을 추가 조회한다. 단순히 언급되지 않은 필드를 모두 복사하거나 필수값으로 채우지 않는다.
3. “조회한 주문을 처리”: 앞 STEP에 ordNo 출력이 정의되어 있으면 previous_steps의 정의로 Binding 작성. 새 주문 식별 출력이나 최종 출력이 필요하면 해당 출처 API의 Response Outputs를 조회한다.
4. 단순 설정 매핑이며 후속·최종 응답 필드가 필요 없는 STEP: KB만 조회한 뒤 StepMappingResult를 반환한다. 도구 3개를 모두 호출하도록 추가 턴을 소비하지 않는다.

## 6. 프롬프트 설계

### 6.1 에이전트 공통 프롬프트

아래는 `prompts.py`에 적용한 시스템 프롬프트다. 응답 필드·타입은 Pydantic Structured Outputs에 맡기며 의미 판단과 자료 선택 규칙을 기술한다.

```text
## 역할
당신은 승인된 업무 단계와 API 자료를 대조해 사용자 조건을 요청 파라미터의 경로·값·출력 참조로 매핑하는 시나리오 매핑 분석가다.

## 목표
현재 승인 STEP의 입력 매핑 후보를 작성한다. 고정된 업무 순서와 API는 변경하지 않는다.
후보가 Baseline을 대체하는지 여부는 백엔드가 비교하므로, 변경 여부를 미리 확정하거나 같은 값일 것이라는 이유로 후보를 생략하지 않는다.

## 판단 순서
1. ParameterKB를 기본 조회하여 의미·별칭·규칙과 schema의 파라미터 경로·타입·XML 위치를 확인한다.
2. 사용자 조건과 단계별 구분값을 현재 요청 구조에 매핑하고, following_steps의 intent_task.conditions 및 input_dependencies/output_consumers에서 조회 결과를 사용하는 업무를 확인한다. 모든 요청 필드를 채우지는 않는다.
3. 기존 기본값·설정 자체를 확인하거나 해석해야 할 때만 Baseline을 추가 조회한다. 백엔드의 값 비교만을 위해 조회하지 않는다.
4. output_consumers가 있으면 현재 API의 Response Outputs를 조회하고 후속 업무에 필요한 식별 출력을 정의한다. input_dependencies의 출처 출력이 previous_steps에 없으면 출처 API의 Response Outputs를 먼저 조회한다. 이미 정의된 출력을 사용할 수 있으면 그 정의를 참조한다.
5. 필요한 자료를 바탕으로 입력 후보·필요 출력·Binding·미해결 항목을 제공된 응답 스키마로 반환한다.

## 매핑 판단 규칙
- required, requiredDeclared, required_state 및 필수/선택 여부는 판단에 사용하지 않는다. 필수값 누락이나 전체 필드 완성 여부를 분석하지 않는다.
- 근거가 확인되는 값만 fixed로 작성한다. 코드 문자열의 앞자리 0을 유지한다.
- Baseline과 schema의 EXAMPLE_ONLY 값·예시를 검증된 업무값으로 간주하거나 그대로 복사하지 않는다. 추가 업무 규칙은 검증 상태와 적용 범위를 확인한다.
- 이전 STEP의 실제 응답값은 아직 없으므로 필요한 값은 기존 출력 정의를 참조하는 Binding으로 표현한다. 없는 출력 이름이나 경로를 임의로 만들지 않는다.
- 대체가 필요할 수 있지만 값이나 의미가 모호한 경우에만 unresolved 또는 run_input으로 표시한다. 사용자가 언급하지 않은 항목을 모두 미해결로 나열하지 않는다.
- 제공된 자료의 source_id·JSON Pointer·짧은 인용을 근거로 사용한다. 자료 부족으로 확인할 수 없는 내용은 확인된 것처럼 작성하지 않는다.
- Canonical은 별도 도구로 요청하지 않는다. KB에 함께 제공되는 schema를 사용한다.

## 조회 결과 의존성 처리
- 결과를 사용하는 업무가 있으면 outputs·bindings를 비워 두거나 일반적인 unresolved만 작성해서 조회를 생략하지 않는다.
- 출력 정의가 없다는 것은 응답 자료가 없다는 뜻이 아니다. Response Outputs를 실제로 조회한 뒤 연결 가능성을 판단한다. API 선택 당시의 확인 불가 문구로 현재 자료 조회를 생략하지 않는다.
- 생산 STEP은 조회한 응답 필드 중 소비 업무에 필요한 것만 outputs로 정의한다. 소비 STEP은 실제 입력의 source=bind와 ref를 bindings의 binding_id에 연결한다.
- 이전 STEP 출력이 빠졌더라도 출처 API에서 확인한 응답 경로로 Binding을 제안할 수 있다. 백엔드가 조회 자료와 일치하는 정의만 이전 outputs에 보완한다. 이전 API나 입력·업무 순서는 바꾸지 않는다.
- 조회 후에도 대응을 확정할 수 없으면 unresolved.dependency_ids에 해당 관계 ID를 넣고 확인한 자료·부족한 업무 의미를 구체적으로 적는다. 관계와 무관한 미해결 항목의 dependency_ids는 빈 배열이다.
- 의존성의 출처가 ambiguous이면 임의로 STEP을 선택하지 말고 해당 dependency_id를 미해결로 기록한다. 필수 여부로 연결할 필드 개수를 결정하지 않는다.

## 작성 규칙 및 제약사항
- assertions는 빈 배열로 둔다. validate_mapping은 호출하지 않는다.
- 사용자에게 질문하거나 실제 업무 API를 호출하거나 Baseline 원본을 수정하지 않는다.
- Baseline 대체 여부·비교 메타데이터·전체 tasks 조립은 백엔드가 처리한다.
```

### 6.2 STEP별 입력 계약

기존 JSON 입력에 input_dependencies·output_consumers를 추가하고 following_steps의 각 항목에 intent_task를 포함한다. 기본/조건부 조회 규칙은 시스템 지시와 ToolRegistry에서 제어한다. 별도 캐시 자료나 고정된 네 조회 결과는 추가하지 않는다.

```json
{
  "current_step": {},
  "previous_steps": {},
  "intent_task": {},
  "original_question": "...",
  "following_steps": [{"step_id":"2-1","intent_task":{"sequence":2,"conditions":"1번 업무에서 조회한 주문을 처리한다."}}],
  "approved_source_id": "approved",
  "input_dependencies": [],
  "output_consumers": [{"dependency_id":"D-1-to-2","source_step_id":"1-1","source_api_id":"승인된 출처 API ID","consumer_task_sequence":2,"conditions":"1번 업무에서 조회한 주문을 처리한다.","status":"resolved"}]
}
```

`current_step`은 고정 계획에서 처리 중인 승인 STEP, `previous_steps`는 앞서 완료된 STEP 결과, `intent_task`와 `original_question`은 승인된 의도분석 정보와 원문 요청이다. `following_steps`는 이후 고정 STEP, `approved_source_id`는 승인 자료 출처 식별자다. 앞 단계 결과는 전체 대화 이력 대신 이 구조화된 값으로 전달된다.

### 6.3 Pydantic Structured Outputs 계약

`output_models.py`의 `StepMappingResult` 모델에서 JSON Schema를 만들고 `text.format.type=json_schema`, `text.format.strict=true`로 전달한다. 출력 필드와 중첩 항목은 스키마가 제어하며, `ToolRegistry.finish()`도 같은 Pydantic 모델로 응답을 파싱한다. 이는 형식·타입 제어다. 별도의 백엔드 매핑 검증은 basic 모드에서 비활성이고, validated 모드에서는 보충 계획서의 inputs·outputs·bindings 항목만 검사한다.

| 필드 | 내용 |
|---|---|
| `step_id` | 백엔드가 부여한 고정 단계 ID |
| `inputs` | 사용자 조건에 해당하는 요청 경로별 매핑 후보. 같은 값도 후보로 전달 가능 |
| `outputs` | 후속 단계 또는 최종 결과에서 참조할 현재 응답 출력 정의 |
| `bindings` | 앞 단계 출력에서 현재 요청으로 연결하는 참조 |
| `assertions` | 빈 배열 유지 (응답 검증 조건 생성 제외) |
| `unresolved` | 확정되지 않은 항목·이유·필요한 입력 |

각 Pydantic `inputs` 항목은 `field`, `parameter_path`, `xml_path`, `type`, `source`, `origin`, `value`, `ref`, `reason`, `evidence`를 모두 가진다. 값이 없는 위치는 null로 표현하고, 근거는 `{source_id, source_pointer, quote}` 객체의 배열이다. `field`는 표시용 이름이고 식별 기준은 `parameter_path`다. 값 공급 방식인 `source`는 다음 네 종류로 한정한다.

| source | 의미 |
|---|---|
| `fixed` | 원본 요청 또는 확인된 지식으로 정해진 값 |
| `bind` | 앞 단계의 출력 참조 |
| `run_input` | 실행 시 사용자가 넣을 항목으로 정의된 값 |
| `unresolved` | 의미·매핑·값을 확정하지 못한 항목 |

`origin`은 값이나 매핑의 기원이며 `user_condition`, `schema`, `parameter_kb`, `previous_output`, `run_input`, `unresolved` 중 하나다. 예를 들어 사용자 조건은 `source: fixed, origin: user_condition`, 앞 단계 응답은 `source: bind, origin: previous_output`으로 표현한다. 근거가 없는 값을 origin만 지정해 확정하지 않는다.

`value`는 JSON 타입을 보존한다. `source: bind`이면 `value`는 null, `ref`는 `bindings` 목록의 `binding_id` 문자열이다. `fixed`이면 값이 있고 `ref`는 null이다. `run_input`과 `unresolved`는 `value`, `ref`를 null로 두고 필요한 내용을 기록한다. `{{1-1.ordNo}}`처럼 값에 참조를 섞는 템플릿 형식은 사용하지 않는다.

각 Pydantic `bindings` 항목은 `binding_id`, `from`, `to_parameter_path`를 모두 가진다. 값이 없는 출처 메타데이터는 null이며, `from`은 `from_step_id`, `output_name`, `response_key`, `content_type`, `response_path`, `path_type`, `row_scope` 필드를 가진다. `from`은 `from_step_id`, `output_name`, `response_key`, `content_type`, `response_path`, `path_type`, `row_scope`를 가진 구조화된 참조다. 출발 출력의 이름·경로·타입과 도착 입력의 전체 경로를 대조한다.

각 Pydantic `outputs` 항목은 `name`, `response_key`, `content_type`, `response_path`, `path_type`, `type`, `row_scope`, `evidence`를 모두 가진다. 값이 없는 위치는 null, 근거는 `{source_id, source_pointer, quote}` 객체 배열로 표현한다. `name`은 단계 안에서 고유해야 한다. `row_scope`는 해당 값이 속한 응답 행의 경로이며, 단일 값이고 행 범위가 없으면 null이다. 경로만으로 다중 행 처리 의미를 추측하지 않는다.

유지할 Pydantic 모델의 Assertion 항목은 `name`, `response_path`, `operator`, `expected`, `evidence`로 구성된다. 다만 임시 분석 모드에서는 프롬프트가 assertions를 빈 배열로 요구하므로 항목을 생성하지 않는다.

`evidence`는 `{source_id, source_pointer, quote}` 항목의 배열이다. `source_pointer`는 원본 JSON의 JSON Pointer이며, XML 응답 위치인 `response_path`와 구분한다. `quote`는 근거가 되는 짧은 원문 구절이다.

`unresolved` 항목은 기존 reason·required_input·parameter_paths·evidence에 dependency_ids(문자열 배열)를 추가한다. 의존성 판단 불가 항목에는 해당 ID를 넣고 다른 미해결 항목은 빈 배열을 사용한다. 백엔드는 이를 최상위 이슈에 보존하고 STEP에는 관련 issue_id를 배치한다. Pydantic Structured Outputs 스키마에도 이 필드를 포함한다.

`StepMappingResult`의 필드 구조는 유지한다. LLM은 baseline_value·baseline_value_source·change_kind를 작성하지 않으며, 백엔드가 비교 후 각 input에 덧붙인다. 후보의 source=fixed는 값의 공급 방식을 뜻하며 Baseline을 실제로 대체한다는 확정 판정이 아니다.

## 7. 백엔드 규칙 적용과 IR 초안

### 7.1 백엔드의 Baseline 비교와 대체 여부 결정

백엔드는 LLM이 Baseline을 조회했는지와 관계없이 현재 STEP의 Baseline을 내부적으로 읽는다. LLM 결과의 전체 parameter_path를 기준으로 비교하며, 타입과 앞자리 0을 보존한다. 후보가 Baseline과 같아도 비교 결과를 미리보기에서 확인할 수 있도록 유지한다. 언급되지 않은 요청 필드는 전체 목록으로 만들어내거나 임의 값으로 채우지 않는다.

| 후보 상황 | 백엔드 change_kind | 처리 |
|---|---|---|
| fixed이며 Baseline 값과 타입·값이 동일 | unchanged | 후보 유지, 변경 없음 표시 |
| fixed이며 Baseline 값과 다름 | replace | 후보 값으로 대체할 항목 표시 |
| bind이며 앞 STEP의 출력 참조 사용 | response_binding | 실제 응답값 대신 구조화된 참조 유지 |
| run_input 또는 unresolved | input_needed | 값 확정 없이 필요한 입력·사유 표시 |
| fixed이지만 Baseline 문서/해당 경로가 없어 비교 불가 | comparison_unavailable | 대체라고 단정하지 않고 비교 불가 사유 표시 |

- 기본 비교 메타데이터 `baseline_value`, `baseline_value_source`, `change_kind`를 유지한다. 비교 불가를 구분하기 위해 `baseline_present`와 `comparison_reason`을 백엔드 메타데이터로 추가한다. 문서에 null 값이 있는 경우와 경로 자체가 없는 경우를 구분한다.
- EXAMPLE_ONLY Baseline과의 비교는 기존 예시값 대비 차이를 나타낸다. 비교를 마쳤다고 검증된 실행값이 되는 것은 아니다.
- Backend의 Canonical 읽기는 API 기술 정보와 KB schema 보완에 사용한다. 모델의 schema 조회 호출로 위장하거나 조건부 조회 완료로 세지 않는다.
- source·origin·reason·evidence는 LLM 후보의 판단 근거를 유지한다. 기존 설정 해석에 Baseline 근거를 사용한 경우와 백엔드가 비교만 수행한 경우를 구분한다.
- 비교 결과 채택을 위해 LLM을 다시 호출하지 않는다. 기존 unresolved를 보존하고 새 정보 부족 항목을 병합한 뒤 IR을 조립한다.

### 7.2 신규 초안 모델

새 초안은 `ir_version: approved-selection-draft-v1`로 구분한다. 첨부 형식의 업무별 계층 구조를 사용하되 실행 기능은 추가하지 않는다. 아래 구조가 저장 파일과 서버 응답 `ir`에 공통으로 적용되는 출력 계약이다.

#### 최상위 구조

| 필드 | 내용 |
|---|---|
| `scenario_id` | 백엔드가 발급하는 시나리오 식별자 |
| `version` | 개별 시나리오 내용의 수정 버전, 최초 1 |
| `created_at` | 생성 시각, 시간대가 포함된 ISO 8601 문자열 |
| `ir_version` | JSON 출력 형식의 버전 |
| `original_question` | 입력 승인본의 원본 요청 |
| `status` | `draft` 또는 `needs_input` |
| `sources` | 입력 승인본, 원본 파일 이름, 실제 조회한 파라미터 자료 목록 |
| `tasks` | 의도분석의 업무 정보와 각 업무에 속한 `steps` |
| `final_outputs` | 이후 실행 시 최종 결과로 제공할 출력 참조 목록 |
| `unresolved` | 전체 미해결 항목과 해결 기록의 원본 목록 |
| `generation` | IR 생성 설정과 실제 호출 횟수·토큰·처리시간 |

`draft`는 구조 검증을 통과한 작성 결과라는 뜻이며 실제 API 성공이나 실행 준비 완료를 뜻하지 않는다. 실행 입력 또는 열린 미해결 항목이 있으면 `needs_input`으로 표시한다. 구조 오류가 있으면 오류 응답으로 반환하고 완성된 IR 초안 파일로 저장하지 않는다.

시나리오 ID와 생성 시각은 백엔드가 작성한다. 이번 버전의 재생성은 새 ID와 `version: 1`로 저장한다. 같은 ID를 수정하는 기능을 추가할 때만 version을 증가시킨다. `ir_version`과 개별 시나리오의 version은 서로 다른 값이다.

#### sources와 근거 연결

- `sources.approved`는 `source_id`, `file`, `version`을 갖는 입력 승인본 기록이다. 승인본에 버전이 없으면 version은 null이다.
- `sources.source_files`는 승인본의 의도분석·API 선택 원본 파일 이름을 그대로 보존한다. 실제로 읽지 않은 원본의 버전이나 내용을 추정하지 않는다.
- `sources.artifacts`는 실제 조회한 문서별 `source_id`, `kind`, `selected_api_id`, `file`, `version` 목록이다. kind는 `canonical_schema`, `parameter_knowledge`, `common_knowledge`, `baseline`, `response_outputs` 중 하나다.
- 원본 문서에 명시적인 버전이 없으면 version은 null이다. 파일 이름의 해시를 문서 버전으로 간주하지 않는다. 공통 지식처럼 특정 API 하나에 속하지 않으면 selected_api_id는 null일 수 있다.
- 모든 evidence의 source_id는 이 sources에 존재해야 한다. 현재 생성에서 조회하지 않은 그래프·카탈로그·메타데이터의 버전 필드를 임의로 추가하지 않는다.

#### tasks와 steps

| 위치 | 필드 | 내용 |
|---|---|---|
| `tasks[]` | `sequence`, `domain`, `action`, `conditions`, `count` | 입력 `intent_tasks`의 업무 정보를 보존 |
| `tasks[]` | `depends_on` | 선행 업무 sequence의 배열, 없으면 빈 배열 |
| `tasks[]` | `graph_id`, `from_state`, `to_state` | 입력·근거에서 확인되는 정보만 기록, 없으면 null |
| `tasks[]` | `target` | 처리할 대상 집합의 출처 단계·행 범위·선택 건수, 정의하지 못하면 null |
| `tasks[]` | `steps` | 해당 업무의 승인된 단계 목록 |
| `tasks[].steps[]` | `step_id`, `step`, `type`, `edge` | 업무번호-단계번호 ID, 원본 단계 번호, `call`, 업무 단계 이름 |
| `tasks[].steps[]` | `from_state`, `to_state` | 근거로 확인되는 업무 상태, 없으면 null |
| `tasks[].steps[]` | `api` | `api_id`, `method`, `endpoint`, `selector` |
| `tasks[].steps[]` | `inputs`, `outputs`, `bindings`, `assertions` | 6.3절의 구조화된 단계 결과 |
| `tasks[].steps[]` | `expect` | 설명용 기대 업무 상태와 evidence, 정의하지 못하면 null |
| `tasks[].steps[]` | `unresolved` | 최상위 unresolved에 존재하는 관련 issue_id의 배열 |

단계 ID는 첨부 형식에 맞춰 `{path_sequence}-{step}`으로 만든다. 예를 들어 첫 업무의 첫 단계는 `1-1`, 두 번째 업무의 첫 단계는 `2-1`이다. 모든 Binding과 출력 참조는 같은 ID를 사용한다. 전체 매핑 키는 API ID와 요청 전체 경로를 함께 사용한다.

`api.api_id`는 승인본의 전체 selected_api_id를 그대로 사용한다. method와 endpoint는 Canonical Schema에서 가져온다. selector는 근거로 확인된 고정 동작 구분값의 객체이며, 없으면 null이다. 예를 들어 `{"procGb": "P1"}`은 같은 경로의 fixed 입력과 일치해야 한다. selector를 정하지 못한 상태를 구분값이 불필요한 것으로 처리하지 않고 미해결 항목으로 남긴다.

백엔드는 업무 간 Binding과 명시적인 업무 조건에서 확인한 선행 관계를 `depends_on`에 반영한다. 단순히 앞번호 업무라는 이유만으로 의존성을 만들지 않는다. 처리 순서는 고정 계획을 유지하며, 의존성이 불명확하면 미해결 항목으로 남긴다.

`target`은 `{source_step_id, row_scope, count}`로 표현한다. 조회 업무가 선택할 결과 집합을 지정하거나, 후속 업무가 앞 조회 업무에서 선택한 동일 집합을 참조한다. 후속 업무가 원본 응답에서 별도로 대상을 다시 고르는 의미가 아니다. count는 API 호출 횟수나 업무 반복 횟수로 변환하지 않는다. 대상이 단일 주문인지 주문상세 행인지 확정하지 못하면 그 의미를 미해결 항목에 기록한다.

`expect`는 `{state, evidence}` 형식의 기대 상태 설명이다. `assertions`가 실제 응답 경로·연산·기대값을 정의한다. expect가 있다고 실제 응답에서 상태를 검사했다고 간주하지 않는다. 이번 단계 type은 조회·처리를 모두 `call`로 표현하며 `wait`, `poll`, 별도 `verify`를 추가하지 않는다. 기존 `ScenarioIR`에 맞추려고 가상의 goal이나 graph_id를 만들지 않는다.

#### final_outputs와 미해결 항목

`final_outputs[]`는 `name`, `ref`를 갖는다. ref는 Binding의 from과 같은 구조화된 출력 참조다. 백엔드가 사용자 요청과 기존 outputs에서 확인되는 결과만 선택해 조립한다. 실제 주문번호 등 실행 결과값이나 문자열 템플릿은 채우지 않는다. 적절한 출력이 없으면 빈 배열로 두고 필요 시 미해결 항목에 기록한다.

최상위 `unresolved[]`는 `issue_id`, `status`, `task_sequence`, `step_ids`, `parameter_paths`, `reason`, `required_input`, `resolution`, `evidence`를 갖는다. status는 `open` 또는 `resolved`다. resolution은 해결된 경우의 설명이며 열린 항목에서는 null이다. 단계의 unresolved 배열은 같은 객체를 복제하지 않고 issue_id만 참조한다. 업무 전체에 적용되는 항목은 관련 단계 ID를 모두 기록한다.

입력 승인본의 기존 미해결 항목에는 백엔드가 안정적인 ID를 부여하고 원문 사유를 보존한다. 일부 내용만 해결되었으면 원본 항목을 완전히 해결한 것으로 표시하지 않는다. 새로 발견한 문제는 별도 ID로 추가한다.

#### 내부 결과와 최종 출력의 이름 대응

- 입력 승인본의 `intent_tasks`는 출력 `tasks`로 변환한다.
- 평탄한 단계 결과는 해당 sequence의 `tasks[].steps[]`로 묶는다. 최상위 steps는 만들지 않는다.
- 원본 요청은 `original_question`으로 통일하며 최상위 request는 만들지 않는다.
- 승인 파일 위치는 `sources.approved.file`에 기록하며 별도 source_approved_file은 만들지 않는다.
- 단계의 요청 매핑은 `inputs`로 통일하며 parameters라는 중복 출력 필드는 만들지 않는다.
- 에이전트는 6.3절의 단계 결과만 작성한다. 시나리오 식별 정보, api 객체 조립, sources, tasks, depends_on, target, expect, final_outputs, generation은 백엔드가 확인된 자료와 단계 결과로 조립한다.
- `generation`은 `config`와 `usage`를 갖는다. config는 8.3절의 화면 설정, usage는 `llm_calls`, `input_tokens`, `output_tokens`, `total_tokens`, `elapsed_seconds`다. 업무 API 실행 정책은 포함하지 않는다.

### 7.3 파싱 및 자료 확보 확인 범위

Pydantic Structured Outputs 파싱, KB 기본 확보와 조건부 자료 확보를 수행한다. basic 모드는 기존 STEP 식별과 의존성 피드백을 유지한다. validated 모드의 검증은 보충 계획서에 정의한 inputs·outputs·bindings 항목으로 한정하며 STEP/API, 업무 의존성 충족, Assertion·unresolved 검사는 포함하지 않는다. 필수값·전체 필드 완성은 두 모드 모두 검사하지 않는다.

자료 확보 확인은 의미상 모든 매핑이 정확하다는 판정이 아니다. validated 모드에서의 검증 통과도 사용자 조건과 파라미터 사이의 의미 적합성이나 실제 업무 실행 성공을 증명하지 않는다.

### 7.4 저장

- 위치: `data/out/scenario_ir_drafts/`
- 파일 이름은 scenario_id와 version으로 구성하며, 저장된 JSON 본문의 식별 정보와 일치시킨다.
- 기존 `data/out/ir/`의 그래프 기반 결과와 구분한다.
- 재생성하면 새 초안 파일로 저장한다.
- `data/scenarios/`에는 저장하지 않는다.

## 8. 서버와 화면 연결

### 8.1 서버 API

| API | 역할 | 입력·출력 |
|---|---|---|
| `GET /api/approved-selections` | 저장된 승인본 목록 | 파일 이름·원본 요청·승인 상태 목록 반환 |
| `POST /api/scenario-ir-drafts` | 선택 승인본으로 IR 생성 | 입력: `approved_filename`, `generation_config`; 출력: `file`, `ir`, `usage` |

기존 로컬 서버 방식의 단일 생성 요청을 유지한다. 기본 응답은 기존 JSON이며, 화면은 Accept: application/x-ndjson으로 실시간 진행 이벤트를 요청한다. 서버는 같은 연결에서 이벤트를 줄 단위로 즉시 전송하고 마지막 generation_complete에 기존 결과를 담는다. 별도 작업 큐나 폴링 작업 API는 도입하지 않는다.

### 8.2 화면 처리

1. 등록 편집 영역에 **IR 생성 설정**을 표시한다.
2. 기존 승인 버튼은 통합 JSON을 저장한다.
3. 저장 성공과 전체 승인 상태를 확인한 뒤 반환된 파일 이름으로 IR 생성을 요청한다.
4. 생성 중에는 진행 문구를 표시하고 같은 생성 버튼의 중복 클릭을 비활성화한다.
5. 승인 버튼 아래 등록 편집 그리드 밖의 독립 IR 영역에 진행 표와 결과를 표시한다. 성공하면 초안 저장 위치, 상태, 적용 설정과 결과 표를 표시한다.
6. 저장된 승인본 선택 목록과 **IR 다시 생성** 버튼으로 다른 승인본 또는 변경된 설정을 적용한다.
7. 승인 JSON 저장은 성공했지만 IR 생성이 실패한 경우 두 결과를 구분해 표시한다. 재시도 시 기존 승인 파일로 IR 생성만 다시 요청한다.

미해결 항목은 원본 IR JSON에 보존하고 선택 STEP에는 확인 필요 상태와 입력 필요 정보를 표시한다. 이번 화면에는 생성 도중 질문을 띄우거나 답변을 수집해 재개하는 입력 흐름을 추가하지 않는다.

`file://`로 직접 연 경우에는 로컬 서버로 열어야 생성할 수 있다는 안내를 표시한다.

### 8.3 기본 실행 설정과 화면 조정

| 설정 키 | 화면 라벨 | 기본값 | 의미 |
|---|---|---:|---|
| `max_turns` | 최대 모델 호출 횟수 | 16 | 요청 전체에서 모델 응답을 받는 횟수. 한 응답의 여러 TOOL 호출은 모델 호출 1회로 계산 |
| `max_tokens` | 최대 누적 토큰 | 150000 | 요청 전체의 입력·출력 합계. 반복 입력도 합산 |
| `max_seconds` | 최대 생성 시간(초) | 180 | IR 생성 요청의 처리시간 상한 |
| `max_output_tokens` | 호출당 최대 출력 토큰 | 4096 | 개별 모델 응답의 출력 상한 |

기본값은 데모용 초기값이다. 각 단계의 값이 아니라 **IR 생성 요청 전체의 설정**으로 전달한다. 모든 단계가 같은 누적 사용량과 설정을 공유한다.

필요 자료를 추가 조회하거나 매핑 후보를 보완하기 위한 모델 호출도 같은 횟수·토큰 합계에 포함한다. TOOL 자체 호출 횟수를 모델 호출 횟수에 추가하지 않는다.

- 화면에는 정수 입력칸 네 개와 **기본값으로 복원** 버튼을 제공한다.
- 서버가 기본값을 관리하고 화면에 전달해 화면·서버의 초기값을 일치시킨다.
- 기본값의 단일 정의 위치는 `agent/config.py`의 DEFAULTS다. `/api/approved-selections`는 같은 DEFAULTS를 반환한다.
- 변경값은 해당 화면의 현재 설정으로 유지하며 새 생성 요청에 적용한다.
- 생성 버튼을 누를 때 설정을 복사해 전송한다. 진행 중 편집한 값은 다음 생성부터 적용한다.
- 서버는 양의 정수 여부와 `max_output_tokens <= max_tokens`를 확인한다.
- 하네스는 화면 설정을 실제 모델 호출 설정에 반영한다. 사용 가능한 잔여량에 맞춰 개별 출력 한도와 호출 시간을 제한한다.
- 설정 한도에 도달한 경우 생성 실패 사유와 사용량을 화면에 표시하고 완성된 초안으로 저장하지 않는다.
- 설정값과 실제 호출 횟수·입력/출력 토큰·처리시간은 생성 결과에 함께 표시한다.
- 화면에서는 모델 인증 정보를 입력받지 않는다. 모델 연결은 서버의 기존 실행 환경을 사용한다.

### 생성 과정 실시간 표시

- 승인 버튼이 있는 등록 편집 그리드 아래에 독립적인 전체 너비 IR 영역을 둔다. 등록된 시나리오 카드와 같은 부모 컨테이너 너비를 사용하며, 왼쪽 편집 카드나 오른쪽 API 선택 결과 내부에 넣지 않는다.
- 화면의 생성 과정 패널에 전체 턴·단계 내 턴, 단계 ID, 누적 입력/출력/전체 토큰과 화면 경과 시간을 표시한다. 토큰 사용량은 각 LLM 응답이 완료된 시점에 갱신하며 응답을 기다리는 동안 시간 표시는 계속 갱신한다.
- Runtime은 선택적 on_event 콜백으로 llm_request, llm_response, tool_selected, tool_start, tool_result, validation_feedback, step_complete, llm_error 이벤트를 전달한다. 콜백이 없으면 기존 비스트리밍 호출을 유지한다.
- llm_request에는 실제 instructions·input·tools·text·모델 이름을, llm_response에는 Responses 원본 응답·상태·이번 턴 사용량을 표시한다. 도구 결정은 모델 응답에 포함된 tool call을 뜻하며 비공개 내부 추론을 표시하는 기능은 아니다.
- 로그는 LLM 턴별 1행과 도구 호출 ID별 1행으로 묶은 표다. 컬럼은 전체 턴, 단계 내 턴, STEP, 종류/도구, 상태, 소요시간, 토큰(이번/누적), valid다. 요청·응답 컬럼은 두지 않는다. 행을 클릭하면 표 아래 공통 상세 영역에서 요청 프롬프트/인자와 응답 결과를 탭별로 보여준다.
- tool_selected → tool_start → tool_result는 같은 행을 갱신한다. 검증 모드에서는 inputs·outputs·bindings 검증 결과의 valid를 표시하고, basic 모드에서는 해당 없음으로 표시한다.
- LLM 행의 공통 상세 영역에는 실제 instructions·input·tools·text와 원본 응답을 표시한다. 도구 행은 호출 인자와 결과를 표시한다. 유효한 JSON 문자열 인자는 파싱하고 JSON.stringify(value, null, 2)로 들여쓰기·구문 강조해 표시한다. 모든 내용은 텍스트 노드로 렌더링한다.
- 첫 로그 행을 자동 선택하고, 이후에는 사용자 선택과 요청/응답 탭을 유지한다. 선택 행에 결과가 도착하면 상세 영역도 갱신한다. 응답 전에는 대기 상태를 표시하며, 재생성하면 이전 선택·상세를 초기화한다. 키보드로도 도구 이름 버튼과 탭을 조작할 수 있다.
- 모델 요청 시간을 별도로 계측한다. 진행 중 상태와 실패 후 행, 기존 JSONL 저장·다운로드는 유지한다.
- 서버는 generation_start로 시작하고 저장 성공 시 generation_complete, 실패 시 generation_error를 전송한다. 스트림 응답은 HTTP 200 이후에도 실패 이벤트가 올 수 있으므로 화면은 최종 이벤트를 확인한다. 실패하거나 연결이 끊겨도 이미 받은 로그는 유지한다.
- progress.py는 표시용 스냅샷에서 인증 헤더·키·비밀번호와 환경의 API 키 값을 마스킹한다. 원본 모델 입력이나 최종 IR 값은 표시 처리 때문에 변경하지 않는다.
- 상세 이벤트는 화면과 요청별 JSONL 파일에 함께 기록한다. 기존 generation.trace는 유지하고 generation.log_file에 전체 로그 파일 경로를 추가한다. 별도 데이터베이스나 장기 기억 기능은 도입하지 않는다.

### 조건부 자료·백엔드 비교 로그

- KB 기본 조회, Baseline·Response Outputs 조건부 조회는 기존 도구 선택·실행 행과 요청/응답 상세 탭에 표시한다. 사용하지 않은 도구에 가짜 호출 행을 만들지 않는다.
- STEP 자료 확보 이벤트에는 실제 공급한 자료와 미해결 의존성을 기록한다. 생략 사유는 결과의 자료 의존성을 기준으로 표시하며 비공개 LLM 추론을 추측해 기록하지 않는다.
- backend_output_defined는 앞 STEP의 확인된 출력 보완을 별도 백엔드 행으로 기록한다. 요청 탭에는 출처 STEP, 응답 탭에는 보완한 출력·응답 근거를 표시한다. 기존 STEP/LLM 행을 덮어쓰거나 가짜 도구 호출을 만들지 않는다.
- material_check에 input_dependencies·output_consumers 및 실제 조회 자료를 기록하며, validation_feedback에는 필요한 출처 조회나 출력/Binding 보완 이유를 남긴다.
- 백엔드 Canonical 읽기·Baseline 비교는 LLM 도구 호출과 다른 이벤트로 기록한다. LLM 호출 횟수·토큰·도구 선택으로 집계하지 않는다.
- 비교 이벤트에는 STEP·후보 경로·기존 값과 출처·후보 값/참조·change_kind·비교 불가 사유를 포함한다. 마스킹·JSONL·실시간 표시 정책은 기존과 같다.

### 전체 실행 로그 파일 저장

- 생성 요청마다 `data/out/scenario_ir_logs/IRRUN-<생성시각>-<고유ID>.jsonl`을 만든다. 성공·실패·재생성은 각각 별도 파일이다.
- `agent/logging.py`의 GenerationJournal이 이벤트마다 한 줄의 JSON을 기록하고 즉시 flush한다. 파일 기록을 먼저 수행하고 화면으로 전송하므로 연결이 끊겨도 앞선 기록은 보존한다.
- 입력 승인 파일·생성 설정, LLM 프롬프트·출력, 도구 선택·인자·결과·valid, 턴·토큰·시간, 단계 채택, 최종 IR 검증, 완료 결과 또는 오류·traceback을 기록한다. 실제 모델이 공개하지 않은 내부 추론은 기록 대상이 아니다.
- 각 줄에는 run_id, sequence, recorded_at, run_elapsed_seconds가 있다. 성공 시 generation_complete, 예외 시 generation_error를 남기고 파일을 닫는다. 예산 초과·초기 설정 오류에도 이미 생성한 로그를 보존한다.
- progress.snapshot과 같은 인증값 마스킹을 적용한 사본만 로그에 기록한다. 원본 모델 입력·IR 자체를 로그 표시 처리 때문에 변경하지 않는다.
- `generate()`는 JSON 응답 방식과 스트리밍 방식 모두 로깅하며, 성공 응답의 log_file·log_url과 IR의 generation.log_file로 연결한다. 실패 응답/이벤트에도 로그 경로를 전달한다.
- 화면의 로그 파일 경로와 JSONL 다운로드 링크는 시작 이벤트부터 표시하고 실패 후에도 유지한다. 다운로드는 `GET /api/scenario-ir-logs/<파일이름>`을 사용한다. 지정 로그 디렉터리의 생성 파일만 제공한다.
- 상세 로그 파일 자동 삭제·보관 기간 설정은 이번 변경에 추가하지 않는다.

### 8.4 IR 미리보기: 반응형 STEP 상세

- 생성 설정과 승인본 선택, 생성 상태·로그 다운로드를 유지하고 그 아래에 시나리오 STEP 영역을 배치한다. 이 영역은 생성 과정·턴/도구 로그보다 위에 둔다.
- 넓은 화면은 왼쪽 STEP 목록과 오른쪽 선택 STEP 상세로 구성한다. 760px 이하에서는 목록과 상세를 위아래로 배치한다. 목록은 대기·분석 중·초안 완료·확인 필요·실패 상태를 표시하고, 사용자의 STEP 선택은 실시간 갱신 중에도 유지한다.
- 상세 상단에 해당 업무 이름과 **원본 업무 조건**을 통합한다. 이어서 API ID·method·처리 구분값·endpoint, 선택 STEP의 대체 파라미터, Baseline XML을 표시한다.
- XML은 적용 후 미리보기와 원본 Baseline 탭을 제공한다. 고정값을 실제 XML 경로에 반영하고 Binding은 {{출처 STEP.출력명}}, 입력 부족은 {{입력 필요: 필드}}로 표시한다. 변경된 요소만 강조한다. 이 표기는 화면 미리보기 전용이며 실제 API 요청이나 IR의 값 표현을 바꾸지 않는다.
- `ir/xml_preview.py`가 원본 문서를 복사해 XML을 구성한다. 경로·복합 요소·XML 본문을 처리할 수 없으면 해당 사유를 표시하고 원본 Baseline 파일이나 IR 초안을 변경·실행하지 않는다. XML 정보가 없는 과거 결과는 안내 문구를 보여준다.
- 반환 JSON의 `step_previews[step_id]`에 original_xml·applied_xml·applied_lines·changes·warnings를 제공한다. 이는 표시용 데이터이며 저장 IR 및 다음 STEP의 LLM 컨텍스트에 넣지 않는다.
- scenario_steps 이벤트로 고정 STEP 정보를, step_preview 이벤트로 STEP별 결과·업무 조건·XML을 전달한다. 기존 생성 과정·로그 표·행 선택 상세·JSONL 저장은 유지하며 이 화면 이벤트를 LLM 도구 호출로 집계하지 않는다.
- 하단의 업무/단계 및 매핑 후보·Baseline 비교 표를 제거한다. 출력·Binding·Assertion·미해결·최종 출력·근거 자료·생성 설정/사용량의 개별 결과 영역도 표시하지 않는다. 해당 데이터는 원본 IR JSON에 그대로 보존한다. 실행 설정 입력과 생성 과정의 사용량 표시는 유지한다.
- 최하단에는 전체 저장 IR을 2칸 들여쓰기·구문 강조된 **IR JSON · Beautify**로 제공한다. XML·JSON·조건·API 값은 텍스트 노드로 렌더링하고, 로그 선택과 XML 탭은 키보드로도 조작할 수 있게 한다.

기존 그래프 기반 realIRCard 및 실행용 저장 버튼과 분리한 표시를 유지한다.

## 9. 기준 예제의 기대 결과

| 고정 단계 ID | API | 작성할 내용 |
|---|---|---|
| `1-1` | `selectOshpDtlList.do` | 요청의 `001442`를 협력사 코드 요청 경로에 매핑하고 조회 조건 작성 |
| `2-1` | `multiOshpProcess.do` | 정의와 업무 의미를 근거로 `procGb=P1` 매핑, 조회 결과 식별자 연결 |
| `2-2` | `multiOshpProcess.do` | `procGb=P2` 매핑, 같은 대상 식별자 유지 |
| `2-3` | `multiOshpProcess.do` | `procGb=P3` 매핑, 같은 대상 식별자 유지 |

- 조회 결과는 아직 없으므로 주문번호·배송지시번호를 예시값으로 채우지 않는다.
- 세 처리 단계가 같은 조회 대상에 연결되도록 Binding을 작성한다.
- 조회 기간·초기 상태·단계별 조건을 자료로 확정할 수 없으면 미해결 항목으로 남긴다.
- 조회의 `count=1`은 원본 의도분석 값을 유지한다. 이를 전체 시나리오 반복 횟수로 사용하지 않는다.
- 주문 단위와 주문상세 행 단위의 관계가 자료로 확인되지 않으면 건수 해석의 미해결 항목으로 표시한다.
- 추가 조회·검증 API 단계는 만들지 않는다.
- 응답 출력이 필요한 STEP에서만 응답 자료를 조회한다. assertions는 빈 배열이며 업무 성공 조건은 생성하지 않는다.
- 자료가 부족한 현재 예제도 초안을 생성할 수 있으며 이 경우 상태는 `needs_input`이다.
- 각 단계는 KB와 필요한 조건부 자료로 매핑 후보를 반환하고, 백엔드가 Baseline 대비 대체 여부를 표시한다. 정보 부족은 사용자 질문 없이 미해결로 남긴다.

### 9.1 기존 IR 외부 구조 예시 (이전 설계 참고)

아래 JSON은 이전 설계에서 작성한 **2개 업무·4개 단계**의 외부 계층·참조 구조 참고 예시다. 이번 조건부 조회 계획의 실제 산출물 예시나 완료 기준이 아니다. 포함된 Assertion·전체 필드 미해결 요구는 적용하지 않으며, 현재 계획은 후보별 비교 메타데이터와 빈 assertions를 사용한다. 실제 에이전트 실행 결과가 아니며 생성 시각·호출 횟수·사용량은 설명용 값이다. 자료 파일과 대표 요청·응답 경로는 저장소의 실제 정의를 사용했다.

가독성을 위해 inputs는 협력사 코드·동작 구분값·주문번호의 대표 매핑만 표시한다. 이전 예시의 U-QUERY-DETAILS와 U-WRITE-DETAILS는 전체 요청 필드 완성을 요구하던 기록이며 이번 계획에서는 그런 이유만으로 새 미해결 항목을 생성하지 않는다. 이 예시는 즉시 실행 가능한 전문이 아니라, 구조가 완결된 needs_input 초안 JSON이다. 일부 매핑을 찾았더라도 기존 미해결 항목의 나머지 조건은 그대로 보존한다.

파일 이름 예: `data/out/scenario_ir_drafts/SCN-20261101-0001-v1.json`

```json
{
  "scenario_id": "SCN-20261101-0001",
  "version": 1,
  "created_at": "2026-11-01T12:00:00+09:00",
  "ir_version": "approved-selection-draft-v1",
  "original_question": "001442 협력사의 주문을 조회하여 배송완료까지 처리해주세요.",
  "status": "needs_input",
  "sources": {
    "approved": {
      "source_id": "approved",
      "file": "prototype/approved/api-selection-approved-order-shipment.json",
      "version": null
    },
    "source_files": {
      "intent_analysis": "intent-analysis-order-shipment.json",
      "api_selection": "api-selection-order-shipment.json"
    },
    "artifacts": [
      {"source_id":"schema-query","kind":"canonical_schema","selected_api_id":"hshop-openapi:POST:/sc/scb/scbd/selectOshpDtlList.do","file":"data/out/parameters/canonical_schema/hshop-openapi/POST_sc_scb_scbd_selectOshpDtlList.do_565cf478.json","version":"v1"},
      {"source_id":"knowledge-query","kind":"parameter_knowledge","selected_api_id":"hshop-openapi:POST:/sc/scb/scbd/selectOshpDtlList.do","file":"data/out/parameters/parameter_kb/api/hshop-openapi/POST%3A%2Fsc%2Fscb%2Fscbd%2FselectOshpDtlList.do.json","version":null},
      {"source_id":"baseline-query","kind":"baseline","selected_api_id":"hshop-openapi:POST:/sc/scb/scbd/selectOshpDtlList.do","file":"data/out/parameters/baseline/hshop-openapi/POST_sc_scb_scbd_selectOshpDtlList.do_565cf478.json","version":null},
      {"source_id":"response-query","kind":"response_outputs","selected_api_id":"hshop-openapi:POST:/sc/scb/scbd/selectOshpDtlList.do","file":"data/out/parameters/response_outputs/hshop-openapi/POST_sc_scb_scbd_selectOshpDtlList.do_6f48d3c4.json","version":null},
      {"source_id":"schema-process","kind":"canonical_schema","selected_api_id":"hshop-openapi:POST:/sc/scb/scbd/multiOshpProcess.do","file":"data/out/parameters/canonical_schema/hshop-openapi/POST_sc_scb_scbd_multiOshpProcess.do_644f3ca7.json","version":"v1"},
      {"source_id":"knowledge-process","kind":"parameter_knowledge","selected_api_id":"hshop-openapi:POST:/sc/scb/scbd/multiOshpProcess.do","file":"data/out/parameters/parameter_kb/api/hshop-openapi/POST%3A%2Fsc%2Fscb%2Fscbd%2FmultiOshpProcess.do.json","version":null},
      {"source_id":"baseline-process","kind":"baseline","selected_api_id":"hshop-openapi:POST:/sc/scb/scbd/multiOshpProcess.do","file":"data/out/parameters/baseline/hshop-openapi/POST_sc_scb_scbd_multiOshpProcess.do_644f3ca7.json","version":null},
      {"source_id":"response-process","kind":"response_outputs","selected_api_id":"hshop-openapi:POST:/sc/scb/scbd/multiOshpProcess.do","file":"data/out/parameters/response_outputs/hshop-openapi/POST_sc_scb_scbd_multiOshpProcess.do_74622ca5.json","version":null}
    ]
  },
  "tasks": [
    {
      "sequence": 1,
      "domain": "DS",
      "action": "주문조회",
      "conditions": "협력사 코드 001442에 해당하는 주문을 조회한다.",
      "count": 1,
      "depends_on": [],
      "graph_id": null,
      "from_state": null,
      "to_state": null,
      "target": {
        "source_step_id": "1-1",
        "row_scope": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row",
        "count": 1
      },
      "steps": [
        {
          "step_id": "1-1",
          "step": 1,
          "type": "call",
          "edge": "주문 조회",
          "from_state": null,
          "to_state": null,
          "api": {
            "api_id": "hshop-openapi:POST:/sc/scb/scbd/selectOshpDtlList.do",
            "method": "POST",
            "endpoint": "/sc/scb/scbd/selectOshpDtlList.do",
            "selector": null
          },
          "inputs": [
            {
              "field": "venCd",
              "parameter_path": "$.body.data1.data2.data3.venCd",
              "xml_path": "/Root/Dataset[@id=\"dsInput\"]/rows/row/venCd",
              "type": "string",
              "source": "fixed",
              "origin": "user_condition",
              "value": "001442",
              "ref": null,
              "reason": "원본 요청의 협력사 코드를 요청 정의의 협력사코드 필드에 매핑한다.",
              "evidence": [{"source_id":"approved","source_pointer":"/original_question","quote":"001442 협력사"},{"source_id":"schema-query","source_pointer":"/parameters/3/description","quote":"협력사코드"}]
            }
          ],
          "outputs": [
            {
              "name": "ordNo",
              "response_key": "200",
              "content_type": "application/xml",
              "response_path": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row/ordNo",
              "path_type": "XPATH",
              "type": "string",
              "row_scope": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row",
              "evidence": [{"source_id":"response-query","source_pointer":"/outputs/51","quote":"주문번호"}]
            }
          ],
          "bindings": [],
          "assertions": [
            {
              "response_key": "200",
              "content_type": "application/xml",
              "response_path": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row/ordNo",
              "path_type": "XPATH",
              "operator": "type",
              "expected": "string",
              "purpose": "response_structure",
              "evidence": [{"source_id":"response-query","source_pointer":"/outputs/51/type","quote":"string"}]
            }
          ],
          "expect": null,
          "unresolved": ["U-INPUT-1","U-QUERY-DETAILS","U-COUNT"]
        }
      ]
    },
    {
      "sequence": 2,
      "domain": "DS",
      "action": "배송완료 처리",
      "conditions": "1번 업무에서 조회한 주문을 배송완료 상태까지 처리한다.",
      "count": 1,
      "depends_on": [1],
      "graph_id": null,
      "from_state": null,
      "to_state": "배송완료",
      "target": {
        "source_step_id": "1-1",
        "row_scope": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row",
        "count": 1
      },
      "steps": [
        {
          "step_id": "2-1",
          "step": 1,
          "type": "call",
          "edge": "주문 확인 및 출고 진행",
          "from_state": null,
          "to_state": null,
          "api": {
            "api_id": "hshop-openapi:POST:/sc/scb/scbd/multiOshpProcess.do",
            "method": "POST",
            "endpoint": "/sc/scb/scbd/multiOshpProcess.do",
            "selector": {
              "procGb": "P1"
            }
          },
          "inputs": [
            {
              "field": "procGb",
              "parameter_path": "$.body.data1.data2.data3.procGb",
              "xml_path": "/Root/Dataset[@id=\"dsInput\"]/rows/row/procGb",
              "type": "string",
              "source": "fixed",
              "origin": "schema",
              "value": "P1",
              "ref": null,
              "reason": "현재 승인 단계의 업무를 Canonical API 설명의 동작 구분값에 대응시킨다.",
              "evidence": [{"source_id":"schema-process","source_pointer":"/summary","quote":"주문확인(P1)/출고완료(P2)/배송완료(P3) 처리"}]
            },
            {
              "field": "ordNo",
              "parameter_path": "$.body.data1.data2.data3.ordNo",
              "xml_path": "/Root/Dataset[@id=\"dsInput\"]/rows/row/ordNo",
              "type": "string",
              "source": "bind",
              "origin": "previous_output",
              "value": null,
              "ref": "B-2-1-ordNo",
              "reason": "앞 조회 단계가 선택한 같은 대상 행의 주문번호를 연결한다. 전체 식별자 구성은 미해결 항목에 남긴다.",
              "evidence": [{"source_id":"response-query","source_pointer":"/outputs/51","quote":"주문번호"},{"source_id":"schema-process","source_pointer":"/parameters/8/description","quote":"주문번호"}]
            }
          ],
          "outputs": [
            {
              "name": "result",
              "response_key": "200",
              "content_type": "application/xml",
              "response_path": "/Dataset[@id=\"result\"]/rows/row/result",
              "path_type": "XPATH",
              "type": "string",
              "row_scope": "/Dataset[@id=\"result\"]/rows/row",
              "evidence": [{"source_id":"response-process","source_pointer":"/outputs/0","quote":"성공"}]
            }
          ],
          "bindings": [
            {
              "binding_id": "B-2-1-ordNo",
              "from": {
                "from_step_id": "1-1",
                "output_name": "ordNo",
                "response_key": "200",
                "content_type": "application/xml",
                "response_path": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row/ordNo",
                "path_type": "XPATH",
                "row_scope": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row"
              },
              "to_parameter_path": "$.body.data1.data2.data3.ordNo"
            }
          ],
          "assertions": [
            {
              "response_key": "200",
              "content_type": "application/xml",
              "response_path": "/Dataset[@id=\"result\"]/rows/row/result",
              "path_type": "XPATH",
              "operator": "exists",
              "expected": null,
              "purpose": "response_structure",
              "evidence": [{"source_id":"response-process","source_pointer":"/outputs/0/response_path","quote":"/Dataset[@id=\"result\"]/rows/row/result"}]
            }
          ],
          "expect": null,
          "unresolved": ["U-INPUT-2","U-WRITE-DETAILS","U-SUCCESS"]
        },
        {
          "step_id": "2-2",
          "step": 2,
          "type": "call",
          "edge": "출고 완료",
          "from_state": null,
          "to_state": null,
          "api": {
            "api_id": "hshop-openapi:POST:/sc/scb/scbd/multiOshpProcess.do",
            "method": "POST",
            "endpoint": "/sc/scb/scbd/multiOshpProcess.do",
            "selector": {
              "procGb": "P2"
            }
          },
          "inputs": [
            {
              "field": "procGb",
              "parameter_path": "$.body.data1.data2.data3.procGb",
              "xml_path": "/Root/Dataset[@id=\"dsInput\"]/rows/row/procGb",
              "type": "string",
              "source": "fixed",
              "origin": "schema",
              "value": "P2",
              "ref": null,
              "reason": "현재 승인 단계의 업무를 Canonical API 설명의 동작 구분값에 대응시킨다.",
              "evidence": [{"source_id":"schema-process","source_pointer":"/summary","quote":"주문확인(P1)/출고완료(P2)/배송완료(P3) 처리"}]
            },
            {
              "field": "ordNo",
              "parameter_path": "$.body.data1.data2.data3.ordNo",
              "xml_path": "/Root/Dataset[@id=\"dsInput\"]/rows/row/ordNo",
              "type": "string",
              "source": "bind",
              "origin": "previous_output",
              "value": null,
              "ref": "B-2-2-ordNo",
              "reason": "앞 조회 단계가 선택한 같은 대상 행의 주문번호를 연결한다. 전체 식별자 구성은 미해결 항목에 남긴다.",
              "evidence": [{"source_id":"response-query","source_pointer":"/outputs/51","quote":"주문번호"},{"source_id":"schema-process","source_pointer":"/parameters/8/description","quote":"주문번호"}]
            }
          ],
          "outputs": [
            {
              "name": "result",
              "response_key": "200",
              "content_type": "application/xml",
              "response_path": "/Dataset[@id=\"result\"]/rows/row/result",
              "path_type": "XPATH",
              "type": "string",
              "row_scope": "/Dataset[@id=\"result\"]/rows/row",
              "evidence": [{"source_id":"response-process","source_pointer":"/outputs/0","quote":"성공"}]
            }
          ],
          "bindings": [
            {
              "binding_id": "B-2-2-ordNo",
              "from": {
                "from_step_id": "1-1",
                "output_name": "ordNo",
                "response_key": "200",
                "content_type": "application/xml",
                "response_path": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row/ordNo",
                "path_type": "XPATH",
                "row_scope": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row"
              },
              "to_parameter_path": "$.body.data1.data2.data3.ordNo"
            }
          ],
          "assertions": [
            {
              "response_key": "200",
              "content_type": "application/xml",
              "response_path": "/Dataset[@id=\"result\"]/rows/row/result",
              "path_type": "XPATH",
              "operator": "exists",
              "expected": null,
              "purpose": "response_structure",
              "evidence": [{"source_id":"response-process","source_pointer":"/outputs/0/response_path","quote":"/Dataset[@id=\"result\"]/rows/row/result"}]
            }
          ],
          "expect": null,
          "unresolved": ["U-INPUT-2","U-WRITE-DETAILS","U-SUCCESS"]
        },
        {
          "step_id": "2-3",
          "step": 3,
          "type": "call",
          "edge": "배송 완료",
          "from_state": null,
          "to_state": "배송완료",
          "api": {
            "api_id": "hshop-openapi:POST:/sc/scb/scbd/multiOshpProcess.do",
            "method": "POST",
            "endpoint": "/sc/scb/scbd/multiOshpProcess.do",
            "selector": {
              "procGb": "P3"
            }
          },
          "inputs": [
            {
              "field": "procGb",
              "parameter_path": "$.body.data1.data2.data3.procGb",
              "xml_path": "/Root/Dataset[@id=\"dsInput\"]/rows/row/procGb",
              "type": "string",
              "source": "fixed",
              "origin": "schema",
              "value": "P3",
              "ref": null,
              "reason": "현재 승인 단계의 업무를 Canonical API 설명의 동작 구분값에 대응시킨다.",
              "evidence": [{"source_id":"schema-process","source_pointer":"/summary","quote":"주문확인(P1)/출고완료(P2)/배송완료(P3) 처리"}]
            },
            {
              "field": "ordNo",
              "parameter_path": "$.body.data1.data2.data3.ordNo",
              "xml_path": "/Root/Dataset[@id=\"dsInput\"]/rows/row/ordNo",
              "type": "string",
              "source": "bind",
              "origin": "previous_output",
              "value": null,
              "ref": "B-2-3-ordNo",
              "reason": "앞 조회 단계가 선택한 같은 대상 행의 주문번호를 연결한다. 전체 식별자 구성은 미해결 항목에 남긴다.",
              "evidence": [{"source_id":"response-query","source_pointer":"/outputs/51","quote":"주문번호"},{"source_id":"schema-process","source_pointer":"/parameters/8/description","quote":"주문번호"}]
            }
          ],
          "outputs": [
            {
              "name": "result",
              "response_key": "200",
              "content_type": "application/xml",
              "response_path": "/Dataset[@id=\"result\"]/rows/row/result",
              "path_type": "XPATH",
              "type": "string",
              "row_scope": "/Dataset[@id=\"result\"]/rows/row",
              "evidence": [{"source_id":"response-process","source_pointer":"/outputs/0","quote":"성공"}]
            }
          ],
          "bindings": [
            {
              "binding_id": "B-2-3-ordNo",
              "from": {
                "from_step_id": "1-1",
                "output_name": "ordNo",
                "response_key": "200",
                "content_type": "application/xml",
                "response_path": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row/ordNo",
                "path_type": "XPATH",
                "row_scope": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row"
              },
              "to_parameter_path": "$.body.data1.data2.data3.ordNo"
            }
          ],
          "assertions": [
            {
              "response_key": "200",
              "content_type": "application/xml",
              "response_path": "/Dataset[@id=\"result\"]/rows/row/result",
              "path_type": "XPATH",
              "operator": "exists",
              "expected": null,
              "purpose": "response_structure",
              "evidence": [{"source_id":"response-process","source_pointer":"/outputs/0/response_path","quote":"/Dataset[@id=\"result\"]/rows/row/result"}]
            }
          ],
          "expect": {
            "state": "배송완료",
            "evidence": [{"source_id":"approved","source_pointer":"/api_selection_results/3/edge","quote":"배송 완료"}]
          },
          "unresolved": ["U-INPUT-2","U-WRITE-DETAILS","U-SUCCESS"]
        }
      ]
    }
  ],
  "final_outputs": [
    {
      "name": "주문번호",
      "ref": {
        "from_step_id": "1-1",
        "output_name": "ordNo",
        "response_key": "200",
        "content_type": "application/xml",
        "response_path": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row/ordNo",
        "path_type": "XPATH",
        "row_scope": "/Response2XML/Dataset[@id=\"dsOutput\"]/rows/row"
      }
    }
  ],
  "unresolved": [
    {
      "issue_id": "U-INPUT-1",
      "status": "open",
      "task_sequence": 1,
      "step_ids": ["1-1"],
      "parameter_paths": ["$.body.data1.data2.data3.venCd"],
      "reason": "협력사 코드 001442를 출고조회 API의 어떤 입력 필드로 지정하는지, 조회 결과가 해당 협력사의 주문만 포함하는지 확인이 필요하다.",
      "required_input": "venCd 매핑은 정의에서 확인했으나 조회 결과의 협력사 범위 보장과 확인 조건이 더 필요하다.",
      "resolution": null,
      "evidence": [{"source_id":"approved","source_pointer":"/unresolved/0/reason","quote":"협력사 코드 001442를 출고조회 API의 어떤 입력 필드로 지정하는지, 조회 결과가 해당 협력사의 주문만 포함하는지 확인이 필요하다."}]
    },
    {
      "issue_id": "U-INPUT-2",
      "status": "open",
      "task_sequence": 2,
      "step_ids": ["2-1","2-2","2-3"],
      "parameter_paths": [],
      "reason": "조회 결과에서 처리 대상 주문을 지정하는 필드와 P1, P2, P3 단계별 선행 상태 및 처리 가능 조건이 카탈로그와 메타데이터에 없어 확인이 필요하다.",
      "required_input": "주문번호 외 식별자 조합, 선행 상태, 단계별 처리 가능 조건을 확인해야 한다.",
      "resolution": null,
      "evidence": [{"source_id":"approved","source_pointer":"/unresolved/1/reason","quote":"조회 결과에서 처리 대상 주문을 지정하는 필드와 P1, P2, P3 단계별 선행 상태 및 처리 가능 조건이 카탈로그와 메타데이터에 없어 확인이 필요하다."}]
    },
    {
      "issue_id": "U-QUERY-DETAILS",
      "status": "open",
      "task_sequence": 1,
      "step_ids": ["1-1"],
      "parameter_paths": ["$.body.data1.data2.data3.fromDate","$.body.data1.data2.data3.toDate"],
      "reason": "조회 기간과 대표 매핑 외 요청 필드의 적용 여부가 확정되지 않았다.",
      "required_input": "실제 생성 시 전체 요청 필드에 대해 값·실행 입력·미해결 여부를 작성해야 한다.",
      "resolution": null,
      "evidence": []
    },
    {
      "issue_id": "U-WRITE-DETAILS",
      "status": "open",
      "task_sequence": 2,
      "step_ids": ["2-1","2-2","2-3"],
      "parameter_paths": ["$.body.data1.data2.data3.dlvstNo","$.body.data1.data2.data3.dlvstPtcSeq","$.body.data1.data2.data3.ordPtcSeq","$.body.data1.data2.data3.invcNo","$.body.data1.data2.data3.dsrvDlvcoCd"],
      "reason": "대표 매핑 외 처리 요청 필드의 입력값과 단계별 필요 조건이 확정되지 않았다.",
      "required_input": "전체 대상 식별자 및 송장·배송사 등 나머지 요청 필드의 적용 조건과 값을 확인해야 한다.",
      "resolution": null,
      "evidence": []
    },
    {
      "issue_id": "U-COUNT",
      "status": "open",
      "task_sequence": 1,
      "step_ids": ["1-1"],
      "parameter_paths": [],
      "reason": "count=1의 업무 대상이 주문 1건인지 주문상세 행 1개인지 확정되지 않았다.",
      "required_input": "주문과 조회 응답 행의 대응 및 대상 선택 기준을 확인해야 한다.",
      "resolution": null,
      "evidence": []
    },
    {
      "issue_id": "U-SUCCESS",
      "status": "open",
      "task_sequence": 2,
      "step_ids": ["2-1","2-2","2-3"],
      "parameter_paths": [],
      "reason": "result 응답 필드의 존재는 확인되지만 업무 성공을 판정할 정확한 기대값은 확정되지 않았다.",
      "required_input": "성공 결과값과 각 단계의 업무 성공 조건이 필요하다.",
      "resolution": null,
      "evidence": [{"source_id":"response-process","source_pointer":"/outputs/0/description","quote":"성공"}]
    }
  ],
  "generation": {
    "config": {"max_turns":16,"max_tokens":150000,"max_seconds":180,"max_output_tokens":4096},
    "usage": {"llm_calls":12,"input_tokens":18000,"output_tokens":6000,"total_tokens":24000,"elapsed_seconds":42.5}
  }
}
```

## 10. 구현 구조와 대상 파일

프로젝트 루트는 `hyejung/mini_project_2_demo/`다. 아래 항목을 소스에 반영했으며 관련 테스트로 확인한다.

| 순서 | 작업 | 대상 | 완료 기준 |
|---|---|---|---|
| 1 | KB schema 보존·Canonical 기술 정보 보완 | `agent/parameter_tools.py` | 원본 identity/knowledge/schema/provenance와 정확한 출처 제공 |
| 2 | 모델 도구 3개 및 기본/조건부 선택 | `agent/tool_registry.py`, `agent/config.py` | get_request_schema 모델 노출 제거, KB 기본 조회 뒤 필요한 도구만 호출 |
| 3 | 후속 조건·조회 결과 의존성 및 완료 피드백 | `ir/dependencies.py`, `agent/tool_registry.py`, `agent/runtime.py` | 후속 업무 조건 전달, 빈 결과에도 필요한 조회 요구, 확인된 이전 출력 보완 |
| 4 | 매핑 후보 중심 프롬프트 적용 | `agent/prompts.py` | 6.1 적용, 변경 여부·동일값 후보 생략 의무 제거 |
| 5 | Backend 비교와 IR 조립 | `ir/draft_build.py` | replace/unchanged/response_binding/input_needed/comparison_unavailable 구분, 비교 메타데이터 부여 |
| 6 | 화면·로그 | `prototype/scenario-ir-draft.js`, `agent/logging.py` | 도구 호출과 백엔드 비교를 구분하고 후보별 비교 결과 표시 |
| 7 | 회귀 테스트 | `tests/test_scenario_ir_drafts.py`, `tests/test_scenario_ir_ui.py` | 아래 조건 충족 및 승인→생성→저장→미리보기 유지 |

## 11. 검증 계획과 완료 기준

### 11.1 모델 호출 없이 검증할 항목

- 모델 도구가 KB·Baseline·Response Outputs의 3개이며 get_request_schema와 validate_mapping은 노출하지 않는지 확인한다.
- KB schema의 type·enum·format·xml_path가 보존되고 Canonical 보완 정보의 출처가 정확한지 확인한다. KB·Canonical의 API/전체 경로가 섞이지 않아야 한다.
- 기본 KB 조회를 누락한 최종 결과에는 해당 자료만 안내하며, 정상 KB 결과를 받은 뒤 Baseline·Response Outputs를 생략한 결과는 채택할 수 있는지 확인한다.
- 기존 설정을 해석한 후보가 공급되지 않은 Baseline 근거를 사용하는 경우와, 백엔드 비교만 필요한 경우를 구분하는지 확인한다.
- 신규 outputs 정의에 필요한 응답 자료가 없으면 그 자료를 안내한다. previous_steps의 기존 출력만 Binding에 사용하는 경우 불필요한 현재 API 응답 조회를 강제하지 않아야 한다.
- 필요한 앞 STEP의 output이 없으면 출처 응답을 조회한 뒤 확인된 정의만 보완하는지 확인한다. 확인 불가한 참조는 관계 ID와 미해결 사유를 남긴다.
- 필요한 자료 미조회·조회 실패·정상 조회 후 업무 지식 부족을 구분하고, 불필요한 전체 도구 호출이나 무한 반복을 유도하지 않는지 확인한다.
- 백엔드는 LLM의 Baseline 조회 없이도 내부 비교를 수행하며, 같은 값은 unchanged, 다른 값은 replace로 표시한다. `001442`와 정수 1442를 같다고 강제 변환하지 않아야 한다.
- Baseline 문서·경로 부재와 명시적 null을 구분하고, 비교 불가는 comparison_unavailable과 사유로 표시하는지 확인한다. 입력 참조와 정보 부족은 각각 response_binding/input_needed로 유지한다.
- source·origin·evidence·previous_steps·고정 단계·API가 보존되고, 예시값이 검증된 업무값으로 승격되지 않는지 확인한다.
- Pydantic StepMappingResult 파싱, Responses의 output·reasoning·call_id 전달, 실패·거절·출력 한도 처리와 전체 요청의 예산 집계를 유지한다.
- 로그에 조건부 도구의 가짜 실행을 만들지 않고 백엔드 비교를 LLM 사용량으로 집계하지 않는지 확인한다.
- 기존 승인 파일 보존·초안 저장·미리보기·행 선택 상세·JSONL 다운로드·설정 기본값과 검증을 확인한다.
- basic 모드는 기존 검증 비활성 동작을 유지하고, 적용 모드는 보충 계획서 표의 inputs·outputs·bindings 항목만 검증하는지 확인한다. 두 모드 모두 필수 여부·실제 업무 API 호출·사용자 질문은 제외한다.

- IRRUN-20261101-153421 로그의 자료 확보 흐름을 basic 모드에서 재현한다. 적용 모드에서는 outputs/bindings 누락 검증이 아니라 표에 명시된 정의·연결 정합성만 검사하는지 확인한다.
- 명시적 업무 참조·하나뿐인 앞선 조회·모호한 출처·의존성이 없는 요청을 구분하고 후속 업무 conditions를 전달하는지 확인한다.
- basic 모드의 기존 자료 확보 피드백과 적용 모드의 매핑 검증 범위를 구분한다. 적용 모드에서 unresolved 자체는 검사 오류가 아니다.
- 소비 Binding이 실제 입력의 ref 및 목적 경로와 연결돼 있는지 확인한다. 확인된 기존 출력이면 불필요한 재조회를 강제하지 않는다.
- 늦게 보완한 출처 출력이 저장 IR·final_outputs·로그에 반영되고, 원래 입력·API·순서가 유지되는지 확인한다. 같은 출력 이름의 충돌이나 확인되지 않은 경로는 보완하지 않는다.

### 11.2 모델 연결 후 확인할 항목

- 명시적인 값만 매핑하는 STEP은 KB만 조회하고 결과를 반환할 수 있는지 확인한다. 정상적인 최소 흐름은 KB 요청과 결과 작성의 2회 호출이며 추가 조회·수정 시 늘어날 수 있다.
- 기존 기간·설정 해석이 필요한 요청에서는 Baseline을 추가 조회하는지 확인한다.
- 후속 연결·최종 출력용 새 필드가 필요한 STEP은 Response Outputs를 조회하고, 이전에 정의된 출력만 사용하는 STEP은 재조회 없이 Binding을 작성하는지 확인한다.
- 업무 의존성·단계 ID·API ID·P1/P2/P3 구분을 유지하고 후보별 비교가 화면에 나타나는지 확인한다.
- 불필요한 세 도구 전체 호출이 줄어드는지 실제 도구 수·턴·토큰·시간으로 확인한다. 시나리오마다 필요한 자료가 달라 일정 호출 수를 성능 보장값으로 두지 않는다.

### 11.3 작업 완료 기준

로컬 서버의 승인 또는 승인본 선택 후 고정 STEP별 매핑 후보를 생성하고, 백엔드가 Baseline과 비교한 IR 초안을 저장·미리보기까지 연결해야 한다. 모델은 KB를 기본 사용하고 나머지 자료는 필요할 때 조회한다. 네 도구 전체 호출을 STEP 완료 조건으로 사용하지 않는다.

기존 IR의 scenario_id·version·created_at·sources·tasks[].steps[]·final_outputs와 StepMappingResult의 필드 구조를 유지한다. 입력은 조건에 해당하는 후보만 작성하고 백엔드 비교 정보를 부여한다. assertions=[]와 needs_input 상태·검증 비활성 메타데이터를 유지하며, 설정값은 offline-ui.html에서 조정할 수 있어야 한다.

## 12. 참고 자료

- 화면: `prototype/offline-ui.html`
- 승인 처리: `prototype/api-selection-import.js`
- 자료 조회: `src/tap/ui/preprocessing.py`
- 기존 IR: `src/tap/ir/build.py`
- 실제 하네스·설정·도구: `src/tap/agent/runtime.py`, `config.py`, `tool_registry.py`, `parameter_tools.py`, `prompts.py`, `progress.py`, `logging.py`
- 하네스: `hyejung/lecture/5. harness_core.ipynb`
- 고정 계획의 결과 관리: `hyejung/lecture/4. planning.ipynb`
- 단계 의존 참조: `hyejung/lecture/4-1. dependent_plans.ipynb`

프로젝트 내부 파일 경로는 10절의 프로젝트 루트를 기준으로 하며, 강의 노트북 경로는 저장소 루트를 기준으로 한다.
