# Scenario IR 에이전트: 정지·재시도 적용 모드 추가 계획

작성일: 2026-11-01
상태: 2026-11-01 소스 구현 반영. 적용 모드의 후보·최종 재검증 범위는 inputs·outputs·bindings로 한정한다. 최근 범위 조정 후 전체 테스트는 재실행하지 않음.
기준 문서: `scenario-ir-agent-plan.md`의 ParameterKB 기본 조회 + Baseline·Response Outputs 조건부 조회 설계

> 2026-11-12 지금과 다른 점 — 모드별 정책(`basic` · `validated`, 아래 표)은 그대로다. 고르는 방법만 바뀌었다.
> - 모드 select 대신 **'중지조건·재시도' 체크박스**(`generation_options.stop_retry`)로 고른다 (11-01, [scenario-ir-context-compression-plan.md](scenario-ir-context-compression-plan.md)). 켜면 `validated`, 끄면 `basic`. 예전 `generation_mode` 요청도 받는다.
> - 숫자 예산 입력칸은 없어지고 서버가 STEP 수로 예산을 정한다 (11-02, [scenario-ir-budget-plan.md](scenario-ir-budget-plan.md)).
> - 최종 등록 화면은 늘 `validated` 로 생성한다. 확인용 등록 화면은 체크박스 기본값(해제)을 따른다.

이 문서는 기본 동작을 유지하면서 선택 가능한 `validated` 모드를 추가하는 변경분만 분리한 보충 계획이다. 사용자의 구현 요청에 따라 이 문서의 정책을 소스에 반영했으며, 기준 계획서의 기본 동작은 유지한다.

## 적용할 설계: 현재 동작을 기본 모드로 유지 + 정지·재시도 적용 모드 선택

KB 기본 조회와 Baseline·Response Outputs 조건부 조회 구조는 소스에 반영되어 있다. 이번 구현은 이 보충 계획을 소스에 반영한다. 현재 동작을 `basic` 기본 모드로 유지하고, 사용자가 UI에서 `validated` 정지·재시도 적용 모드를 선택했을 때만 추가 정책을 실행하도록 계획한다. 모드 분기·검사기 수정·재시도 정책·UI 선택을 구현했다.

- LLM에는 `get_parameter_knowledge`(기본), `get_baseline_request`(조건부), `get_response_outputs`(조건부)의 **3개 도구**를 제공한다. `get_request_schema`는 모델 도구에서 제외한다.
- ParameterKB는 자연어를 파라미터 경로·값으로 연결하는 기본 자료다. 파라미터의 `identity`, `knowledge`, **`schema`**, `provenance`를 함께 전달한다.
- LLM은 조건의 매핑 후보를 `StepMappingResult`로 작성한다. 후보가 Baseline과 같은지 다른지는 백엔드가 결정한다. LLM에 Baseline을 항상 조회하거나 변경 없는 항목을 미리 제거하도록 요구하지 않는다.
- 백엔드는 Canonical로 KB의 기술 정보를 보완하고 IR의 method·endpoint·content type 등을 구성한다. Baseline은 매 STEP의 후보 비교에 사용하되, 이 내부 사용을 LLM의 Baseline 조회로 세지 않는다.
- 필요한 Response Outputs 자료는 승인 계획의 입력·출력 의존성에 따라 확보한다. validated 모드의 매핑 검증은 도구 자료 확보 여부 외에 업무 의존성·unresolved 객체의 완전성을 검사하지 않는다.
- `client.responses.create()`·Pydantic Structured Outputs·고정 단계·화면 예산 설정·초안 저장·미리보기·실시간 로그·JSONL은 유지한다.
- 기본 모드에서는 기존 자료 확보·피드백 흐름을 유지한다. 적용 모드의 `validate_mapping`과 최종 재검증은 inputs·outputs·bindings에 직접 관련된 검사만 수행한다. 통신 재시도와 매핑 수정은 적용 모드에만 추가한다(5.3~5.6절).
- 두 모드 모두 필수 여부 판단·Assertion 생성·실제 업무 API 실행·사용자 질문은 제외한다. 저장 결과는 계속 `needs_input` 분석용 초안이다. 검증 통과를 API 실행 성공이나 실행 준비 완료로 표시하지 않는다.
- validated 모드의 검증 범위는 사용자가 지정한 inputs·outputs·bindings 항목으로 한정한다. 업무 의존성 완전성, Assertion 금지, 미해결 객체, STEP/API 식별 검사는 매핑 검증 실패 조건에서 제외한다. 통신 재시도·STEP 수정 한도와 저장 전 동일 매핑 재검사는 유지한다.
- 앞서 폐기한 STEP 간 캐시·자료 자동 주입 설계는 이번 계획에 포함하지 않는다.

### 5.3 생성 모드와 완료 검사 분기 (구현 반영)

| 정책 | `basic` — 기본 모드 | `validated` — 정지·재시도 적용 모드 |
|---|---|---|
| 선택 기본값 | 모드 생략·기존 클라이언트·UI 초기 선택 | UI에서 명시적으로 선택 |
| 모델 조회 도구 | 현재 3개 유지 | 같은 3개 유지 |
| 자료 확보·의존성 피드백 | 현재 방식 유지 | 공통 조건 유지, 자료 부족과 매핑 오류를 구분 |
| 매핑 검사 | 비활성 | inputs·outputs·bindings 후보 검사 |
| 일시 LLM 통신 오류 | 현재처럼 추가 재시도 없음 | 논리적 요청마다 최초 실행 + 재시도 최대 1회 |
| 매핑 수정 | 현재 피드백 흐름 유지, 새 수정 한도는 적용하지 않음 | STEP마다 최초 작성 + 수정 최대 1회 |
| 최종 IR 검사 | 비활성 | 저장 전 필수, 오류 원인별 처리 |
| 저장 상태 | 현재 `needs_input` 유지 | 검사를 통과한 분석용 `needs_input` 유지 |

```text
생성 요청 → 모드 검증 및 요청별 정책 확정 → 공통 고정 STEP 목록 구성
  → STEP별 KB 기본 조회·필요한 조건부 조회 → StepMappingResult
      ├─ basic: 현재 파싱·자료 확보 확인 → 채택
      └─ validated:
          → Pydantic 파싱·자료 확보 확인
          → Canonical에서 확인된 누락 기술 정보만 보완
          → validate_mapping
              ├─ 통과 → 백엔드 채택 (최종 확인용 LLM 재호출 없음)
              ├─ 자료 부족 → 필요한 자료만 조회 → 재검사
              ├─ 수정 가능 → 구체적인 피드백 → STEP 수정 1회 → 재검사
              ├─ 업무적으로 확정 불가 → 후보에 unresolved를 표현할 수 있음 (이 검증기에서 검증하지 않음)
              └─ 필요한 자료 오류·수정 후 오류 잔존 → 중단
  → Baseline 비교·전체 IR 조립
      ├─ basic: 현재 저장·미리보기
      └─ validated: 최종 IR 검사 → 통과한 경우에만 저장·미리보기
```

기술 정보 보완은 Canonical에서 확정할 수 있는 누락된 field/type/xml_path 등으로 한정한다. 모델이 명시한 잘못된 값·경로나 업무 판단을 조용히 바꾸어 통과시키지 않는다. 앞 STEP 출력 보완은 검사할 임시 결과에 먼저 반영하고, 전체 후보가 통과했을 때만 확정한다. 검증을 통과한 것과 다른 작성안을 채택하지 않는다.

### 5.4 적용 모드의 validate_mapping 검사 계약

검증 범위는 앞서 합의한 현재 항목 중 **inputs·outputs·bindings에 직접 속하는 검사만**으로 한정한다. 필수값·전체 요청 필드 완성, STEP/API·업무 의존성·unresolved 객체·Assertion 검사는 이 매핑 검증 단계에서 수행하지 않는다. Pydantic Structured Outputs는 모델 응답의 계약을 파싱하는 역할만 유지한다.

| 검증 항목 | 대상 | 현재 확인 내용 | 실패 코드 |
|---|---|---|---|
| 후보 배열 구조 | inputs, outputs, bindings | 각 항목이 객체 배열인지 확인 | `INVALID_MAPPING_OUTPUT` |
| 경로 존재 여부 | inputs | 파라미터 경로가 현재 API 요청 스키마에 있는지 확인 | `PARAMETER_PATH_NOT_FOUND` |
| 이름·경로 중복 | inputs, outputs, bindings | 입력 경로, 출력 이름, Binding ID가 중복되지 않는지 확인 | `DUPLICATE_MAPPING` |
| 기술 메타데이터 일치 | inputs | 입력의 `type`, `xml_path`가 API 스키마와 일치하는지 확인 | `PARAMETER_METADATA_MISMATCH` |
| 출처·매핑 방식 유효성 | inputs | `origin`, `source`가 허용된 값인지 확인 | `INPUT_SOURCE_MISMATCH` |
| 고정값 타입·enum | inputs | 고정값이 요청 타입과 enum에 맞는지 확인 | `VALUE_TYPE_MISMATCH`, `VALUE_ENUM_MISMATCH` |
| 근거 존재·대조 | inputs, outputs | 근거 존재와 실제 자료의 출처·pointer·인용 일치를 확인 | `EVIDENCE_MISMATCH` |
| 값·ref 조합 | inputs | 비고정 입력의 값이 null인지, Binding 외 입력에 ref가 없는지 확인 | `INPUT_SOURCE_MISMATCH` |
| 미해결·런타임 입력 사유 | inputs | `unresolved`·`run_input` 입력에 사유가 있는지 확인. 유효하면 warning 기록 | `INVALID_UNRESOLVED` |
| 출력 정의 일치 | outputs | 활성 Response Outputs의 응답 키·콘텐츠 타입·경로·타입·행 범위와 일치하는지 확인 | `OUTPUT_DEFINITION_MISMATCH` |
| Binding 출처 일치 | bindings | 실제 선행 STEP 출력과 이름·응답 참조 정보가 일치하는지 확인 | `BINDING_SOURCE_MISMATCH` |
| Binding 대상 연결 | inputs, bindings | 대상 경로가 현재 API에 있고 해당 입력이 Binding ID를 참조하는지 확인 | `BINDING_TARGET_MISMATCH` |
| Binding 타입 일치 | inputs, bindings | 선행 출력과 대상 입력 타입이 일치하는지 확인 | `BINDING_TYPE_MISMATCH` |
| 반복 행 범위 일관성 | bindings | 같은 선행 STEP에서 가져오는 Binding들의 행 범위가 일관적인지 확인 | `BINDING_SOURCE_MISMATCH` |

승인 단계·고정 API 목록은 입력 조건으로 사용한다. 후보 `step_id`나 API ID를 매핑 검증 항목으로 비교하지 않는다. Pydantic이 `StepMappingResult` 전체 응답 모양을 파싱하더라도 `assertions` 값의 허용 여부, `unresolved` 사유·dependency ID, 업무 의존성 충족을 이 검증기의 실패 조건으로 삼지 않는다. `unresolved.evidence`는 물론 매핑 검증 대상이 아니다.

출처 근거는 실제 자료와 대조한다. `/current_step/...`는 현재 STEP 객체에서, `/previous_steps/{step_id}/...`는 해당 실행의 이전 STEP 스냅샷에서 해석한다. 구조 객체 인용은 직렬화 공백에 의존하지 않고 실제 값으로 확인한다. Response Outputs에 정확히 대응한 출력 근거는 백엔드가 보완한다. 이 대조는 인용의 존재를 확인하며 LLM의 자연어 의미 판단이 맞는지는 증명하지 않는다.

오류는 `code`, `item_path`, `message`, `expected`, `actual`, `recovery`로 보고한다. 검증 실패는 매핑 수정 재시도 흐름에 전달한다. 매핑 계약 밖의 업무 의존성 누락·미해결 ID·Assertion 오류를 `validate_mapping` 오류로 변환하지 않는다.

### 5.5 적용 모드의 재시도·수정·종료 정책

**통신 재시도와 매핑 수정을 서로 다른 상태로 관리한다.** 관련 기본값·오류 분류·복구 문구는 `agent/config.py`에 두고, Runtime은 요청별 정책을 읽어 실행한다. 기본 모드에는 새 정책을 적용하지 않는다.

| 상황 | 처리 주체·동작 | 한도 또는 종료 조건 |
|---|---|---|
| 일시 LLM 통신 오류 | 하네스의 통신 래퍼가 타임아웃·일시 서버 오류·일시적 429만 대기 후 동일 요청 재시도. 429에 대기 시간이 있으면 따름 | 논리적 LLM 요청마다 최초 + 최대 1회. 다시 실패하면 중단 |
| 인증 실패·잘못된 요청·재시도로 해결 불가한 한도 오류 | 오류를 기록하고 중단 | 통신 재시도 없음 |
| 필요한 자료 미조회 | 명시한 도구·API만 조회한 뒤 검사 재개 | 자료 확보 단계는 매핑 수정 기회로 세지 않음. 같은 부족 상태로 새 자료·작성안 변화 없이 돌아오면 중단 |
| 형식·경로·값·타입·참조 등 수정 가능한 작성안 오류 | 구체적인 검증 결과를 현재 STEP의 LLM 컨텍스트에 전달 | STEP 전체에서 수정 1회. 오류 코드별로 기회를 새로 주지 않음 |
| 수정 후 검사 오류 | 같은 오류·다른 오류 모두 추가 수정 없이 종료 | 유효하지 않은 작성안은 검증 실패. 유효한 미해결 표현은 오류 잔존과 구분하여 채택 |
| 정상 조회 후에도 업무 정보 부족 | 프롬프트에 따라 unresolved 표현을 작성할 수 있음 | unresolved의 사유·dependency_ids는 이 검증기의 실패 조건이 아님 |
| 필요한 자료 파일 누락·손상·API 식별 충돌 | 자료 오류로 중단 | LLM 수정이나 동일 파일 재조회 없음 |

매핑 수정 횟수는 STEP의 전체 생명주기에서 공유한다. 최종 IR 검사 단계에 도달하거나 오류 종류가 바뀌어도 초기화하지 않는다. 수정 중 새 자료가 필요하면 동일 수정 사이클에서 확보하고 검사하며, 조회를 이유로 수정 기회를 늘리지 않는다. 도구 인자·API 범위 오류도 수정 가능한 오류로 구체적으로 안내하고, 적용 모드에서 같은 잘못된 호출을 무제한 반복하도록 두지 않는다.

통신 재시도는 한 계층에서만 수행한다. 계획상 하네스의 통신 래퍼가 담당하고 SDK 자동 재시도는 0으로 유지한다. `llm_transport_max_retries=1`은 최초 요청을 포함한 1회가 아니라 **추가 시도 1회**를 뜻한다. 통신 재시도는 매핑 수정 기회를 소비하지 않고, 재시도마다 새로운 매핑 수정 기회를 부여하지도 않는다. 기존 숫자 예산 설정·집계는 그대로 적용하며 리셋하지 않는다.

실패·미해결은 다음과 같이 구분한다.

- 업무적으로 값을 확정할 수 없는 경우 프롬프트에 따라 `source=unresolved/run_input` 또는 관계별 unresolved로 표현한다. 입력·출력·Binding 검증에 포함된 잘못된 경로·값 타입·참조는 unresolved 표현만으로 무효화되지 않는다.
- 수정 후에도 이 계약의 입력·출력·Binding 오류가 남으면 검증 실패다. 전체 실행의 실패 사유·STEP·오류를 기록하고 초안을 저장하지 않는다.
- 실제로 필요한 자료가 없거나 손상된 경우 자료 오류다. 사용하지 않는 선택 자료의 부재는 중단 조건이 아니다. 단순 Baseline 비교용 문서·경로 부재는 기존 comparison_unavailable 처리를 유지하고, 해당 자료 해석이 반드시 필요한 경우와 구분한다.
- 실패 시 승인 파일·기존 초안·이미 전송한 진행 로그·JSONL은 보존한다. 완료된 앞 STEP의 화면 정보는 중간 결과임을 표시하고 전체 생성 완료로 오인하지 않도록 한다.

### 5.6 적용 모드의 최종 IR 검사와 수정 책임

저장 직전에 STEP별 inputs·outputs·bindings 검증을 다시 수행한다. 승인 STEP 순서·API 기술 정보, Assertion·unresolved 참조, 업무 의존성 충족, selector·depends_on 조립 및 final_outputs 참조는 이 최종 매핑 검증의 실패 조건에서 제외한다. 고정 계획과 백엔드 조립은 그대로 사용하며, 필수값·전체 요청 필드 완성·실제 API 실행도 검사하지 않는다.

| 오류 원인 | 처리 |
|---|---|
| LLM 작성 매핑 오류 | 원인이 되는 STEP과 구체적 오류를 연결. 그 STEP에 수정 기회가 남아 있을 때만 1회 수정 후 재검사 |
| 이미 수정한 STEP의 오류 | 최종 검사라는 이유로 한도를 갱신하지 않고 실패 처리 |
| 입력·출력·Binding 검증 오류 | 해당 STEP의 매핑 수정 한도 안에서만 재시도 |
| 업무적으로 확정 불가한 unresolved | 이 검증기에서 유효성 판정하지 않고 조립된 분석용 초안에 보존 |

앞 STEP 출력이 바뀐 뒤 최종 재검사를 할 때, 각 STEP의 inputs·outputs·bindings만 승인된 한도 안에서 재검사한다. 후속 STEP의 Binding 오류가 확인되면 해당 STEP의 남은 수정 기회 안에서만 처리한다. 검증 결과가 달라졌다는 이유로 새 수정 라운드를 무한히 열지 않는다.

수정이 허용되는 동안 결과를 임시 상태로 관리하고, 모든 검사 통과 후에만 정상 초안 파일을 저장한다. 최종 검사 결과가 통과했다면 별도의 확인용 LLM 호출 없이 백엔드가 채택한다.

### 6.4 적용 모드 전용 지시와 복구 피드백 (구현 반영)

기본 모드는 6.1절의 공통 프롬프트와 기존 피드백을 유지한다. 적용 모드만 서버 CONFIG에서 아래 추가 지시를 결합한다. 출력 스키마는 두 모드에서 같으며 모드명·재시도 횟수·IR 조립 결과를 LLM에게 작성시키지 않는다. validate_mapping은 백엔드 검사이므로 공통 프롬프트의 호출 금지 지시와 충돌하지 않는다.

```text
## 백엔드 검증과 복구
- 적용 모드에서 백엔드는 inputs·outputs·bindings만 검증한다. 업무 의존성 충족, STEP/API 식별, assertions 및 unresolved 객체는 이 검사 오류로 반환하지 않는다.
- 자료 부족 피드백의 CALL_TOOL은 지정된 도구와 승인된 API로 필요한 자료만 조회하라는 뜻이다. 모든 도구를 다시 호출하지 않는다.
- REVISE_MAPPING 피드백을 받으면 code·item_path·expected·actual을 확인해 오류 항목과 직접 연결된 항목을 수정한다. 올바른 업무 순서·API·조건은 유지한다.
- 필요한 자료가 이미 제공돼 있다면 그 자료로 작성안을 수정한다. 판단 근거 없는 값·출력·참조를 만들지 않는다.
- 정상 조회 후에도 업무적으로 확정할 수 없으면 프롬프트에 따라 unresolved로 표현할 수 있다. 단, unresolved 자체의 업무 적정성은 이 검증기의 판정 대상이 아니다.
- 수정 결과는 동일한 StepMappingResult 스키마로 반환한다. 수정 허용 여부·횟수·중단·저장 여부는 백엔드가 결정한다.
- assertions는 빈 배열로 유지하고 실제 업무 API 실행·사용자 질문·Baseline 원본 변경은 하지 않는다.
```

복구 피드백에는 5.4절의 오류 목록 외에 `phase`(자료 확보/매핑/최종 IR), `step_id`, `repair_remaining`을 포함한다. CALL_TOOL이면 `needed_materials`에 실제 도구명·API를 제공하고, REVISE_MAPPING이면 원본에서 확인된 기대값·현재값과 수정 대상을 제공한다. 단순히 “다시 검토하세요”라는 피드백만 반복하지 않는다. 검증 오류를 문서 내용이 아닌 백엔드의 검사 결과로 구분해 전달한다.

통신 오류의 대기·동일 요청 재시도와 STOP 판정은 LLM 프롬프트에 맡기지 않는다. 하네스가 수행하고 화면·JSONL에 사유를 기록한다. 최종 IR 오류를 수정하는 경우에도 LLM에는 해당 STEP의 작성안·관련 앞 STEP 출력·검증 오류를 전달하며 전체 IR의 API·순서·백엔드 식별 정보를 다시 작성시키지 않는다.

### 8.3.1 생성 모드 선택과 서버 정책 (구현 반영)

(11-01 기록) 숫자 예산의 기본값·입력칸·generation_config는 그대로 유지하고 **생성 모드** 선택을 별도로 추가했다. 지금은 위 머리말처럼 체크박스 · STEP 예산으로 바뀌었다.

| UI 표시 | 요청 값 | 설명 |
|---|---|---|
| 기본 모드 (기본 선택) | `basic` | 현재 조회·매핑 후보 분석·피드백·저장 동작 유지 |
| 정지·재시도 적용 모드 | `validated` | inputs·outputs·bindings 검사, 통신 재시도 1회, STEP 수정 1회, 최종 재검사 적용 |

- `agent/config.py`에 기본 모드 `basic`, 허용 모드와 표시명, 아래 모드별 정책을 정의한다. 기본값의 단일 정의 위치를 유지하고 서버가 목록·기본값을 화면에 제공한다.
- generation_mode가 없는 기존 요청은 basic으로 처리한다. 허용되지 않은 값은 설정 오류로 거부하고 LLM을 호출하지 않는다. 잘못된 모드를 조용히 다른 모드로 바꾸지 않는다.
- 생성 버튼 클릭 시 모드와 숫자 설정을 복사하고, 서버가 요청별 CONFIG 스냅샷을 만든다. 다른 요청이나 실행 도중의 UI 상태가 해당 정책을 바꾸지 못하게 한다.
- 생성 중 모드 선택을 비활성화하고 현재 실행 모드를 표시한다. 종료 후 다른 모드로 다시 생성할 수 있으며, 이는 새 요청·새 로그·새 초안이다. 기존 실행을 중간 전환하거나 자동 재개하지 않는다.
- 초기 선택과 기본값 복원은 basic이다. 승인 직후 자동 생성과 승인본 선택 후 다시 생성 모두 같은 선택값을 전달한다.
- 재시도·수정 횟수는 모드별 서버 CONFIG로 관리한다. 이번 UI는 모드 선택만 제공하며 해당 정책 수치를 직접 편집하는 입력은 추가하지 않는다.

| 서버 정책 키 | basic | validated |
|---|---|---|
| `mapping_validation` | false | true |
| `final_ir_validation` | false | true |
| `llm_transport_max_retries` | 0 | 1 (논리적 요청별 추가 시도) |
| `mapping_repair_limit_per_step` | null (새 제한 정책 미적용) | 1 (최종 검사에서의 수정까지 공유) |

요청 계약 예시는 다음과 같다. generation_mode는 숫자 4개를 검증하는 generation_config 안에 넣지 않는다.

```json
{
  "approved_filename": "api-selection-approved-order-shipment.json",
  "generation_mode": "validated",
  "generation_config": {
    "max_turns": 16,
    "max_tokens": 150000,
    "max_seconds": 180,
    "max_output_tokens": 4096
  }
}
```

성공 IR의 `generation.execution_mode`에 선택 모드, `generation.policy`에 실행한 모드별 정책 사본을 기록한다. 기존 `generation.mode="baseline_replacements"`는 분석 종류이므로 덮어쓰지 않는다. `generation.config`는 기존 숫자 4개를 유지하고 프롬프트·인증 정보는 정책 메타데이터에 넣지 않는다. 과거 IR·로그에 모드가 없으면 화면에서는 기본 모드(기존 결과)로 해석하며 저장 파일을 다시 쓰지 않는다.

저장 성공 시 기본 모드는 `generation.validation={mapping:false, required_fields:false, final_mapping:false}`, 적용 모드는 `{mapping:true, required_fields:false, final_mapping:true}`로 기록한다. 적용 모드가 검사 실패한 경우 해당 true 값을 가진 성공 IR을 만들지 않고 실패 로그에 단계·검사 결과를 남긴다. 미해결 업무 정보는 두 모드 모두 보존하며 검사 통과를 실제 업무 성공으로 표시하지 않는다.

### 10.1 모드 전환 추가 구현 대상 (구현 반영)

| 작업 | 대상 | 완료 기준 |
|---|---|---|
| 모드·정책 기본값과 검증 | `agent/config.py`, `ui/serve.py` | 기본 basic, 생략 시 호환, 잘못된 값 거부, 요청별 CONFIG, 기존 숫자 4개 계약 보존 |
| 후보 단위 검사와 오류 코드 | `agent/mapping_validation.py`, `agent/parameter_tools.py`, `agent/tool_registry.py` | 5.4절의 inputs·outputs·bindings 검사만 적용하고 각 오류에 기대값·현재값·복구 행동 제공 |
| 통신 재시도·STEP 수정 및 종료 | `agent/runtime.py`와 별도 통신 재시도 래퍼 | CONFIG 기반 추가 시도 1회, SDK 재시도 중복 없음, STEP 수정 1회와 최종 검사 간 한도 공유 |
| 모드별 프롬프트 | `agent/prompts.py` | 기본 프롬프트 유지, 적용 모드만 6.4절 지시 추가, 같은 Structured Outputs 사용 |
| 최종 검사·저장·재검사 | `ir/draft_validate.py`, `ir/draft_build.py` | inputs·outputs·bindings만 재검사, 매핑 수정 한도 공유, 실패 IR 저장 방지 |
| 모드 선택·검사·복구 로그 | `web/offline-ui.html`, `web/scenario-ir-draft.js`, `agent/logging.py` | 생성 시작 시 모드 고정, 현재 STEP·XML·로그·IR Beautify 유지, 모드·검사·재시도 사유 기록 |
| 모드별 회귀 검증 | 기존 `tests/`와 필요한 추가 테스트 | 기본 동작 보존 및 11.3절의 적용 모드 조건 확인 |

### 11.3 모드 전환·정지·재시도 추가 검증 계획

실제 유료 모델 호출 없이 모드 분기·검증기·가짜 응답/예외·대기 함수 대체를 사용해 아래 조건을 먼저 검증한다. 실제 모델 연결 검증은 11.2절의 기준에 모드별 정책 확인을 더한다.

- UI 초기값·기본값 복원·generation_mode 생략 요청이 모두 basic이며, 기본 모드의 조회·피드백·저장·예산·화면·로그 동작이 바뀌지 않는지 확인한다.
- validated 선택이 승인 후 자동 생성과 승인본 재생성 모두에 전달되고, 생성 중 선택을 바꿀 수 없으며 동시 요청의 정책이 섞이지 않는지 확인한다. 잘못된 모드는 LLM 호출 전에 거부해야 한다.
- 두 모드의 LLM 도구는 같은 3개이고, 적용 모드는 LLM의 validate_mapping 호출 없이도 백엔드 검사를 반드시 실행하는지 확인한다.
- 적용 모드는 5.4절 표의 inputs·outputs·bindings 검사만 반환하는지 확인한다. STEP/API 불일치, 업무 의존성 누락, Assertion, unresolved 객체 검사가 매핑 오류로 나타나지 않아야 한다.
- 입력 경로·중복·기술 메타데이터·출처·고정값 타입/enum·값/ref 조합·사유, 출력명·응답정의·근거, Binding ID·출처·대상·타입·행 범위 오류가 표의 코드와 위치로 보고되는지 확인한다.
- 응답 경로에서 산출할 수 있는 null `row_scope`가 정규화되어 정상 출력 정의를 오탐하지 않는지, 명시적으로 잘못된 `row_scope`는 여전히 오류인지 확인한다. `/current_step/...`와 `/previous_steps/{step_id}/...` evidence pointer 및 객체 필드 인용은 해당 실행 입력·원본 자료의 실제 값으로 대조하고, 수정 피드백이 유효 근거의 삭제를 유도하지 않는지 확인한다.
- 현재 API에 없는 입력 후보는 거부하고, 선행 출력·대상 입력이 없으면 Binding 검사가 오류를 내는지 확인한다. 반면 의존성 충족 여부와 unresolved 사유·dependency ID 자체는 이 매핑 검증에서 검사하지 않아야 한다. unresolved evidence도 검사 대상이 아니다.
- 자료 부족은 먼저 필요한 도구만 조회하며, 새 자료 없이 같은 부족 상태가 반복되면 적용 모드에서 중단하는지 확인한다. 자료 확보가 매핑 수정 기회를 소비하거나 갱신하지 않는지 확인한다.
- 타임아웃·일시 서버 오류·일시적 429는 논리적 요청별 추가 1회만 시도하고 대기 시간을 지키는지 확인한다. 인증·잘못된 요청·비일시 오류는 즉시 중단하며 SDK 재시도로 실행 수가 늘어나지 않아야 한다.
- 매핑은 STEP별 수정 1회 후 같은 오류뿐 아니라 다른 오류가 남아도 종료하고, 오류 코드가 바뀌거나 최종 검사로 넘어가도 한도가 초기화되지 않는지 확인한다. 통신 재시도와 매핑 수정 상태를 구분해야 한다.
- 업무 정보 부족만 유효한 미해결로 채택되고, 잘못된 경로·끊어진 참조를 남긴 채 상태만 변경하여 통과시키지 못하는지 확인한다.
- 필요한 자료 누락·손상은 재시도 없이 중단하고, 무관한 선택 자료 부재나 단순 Baseline 비교 불가는 기존 처리로 유지하는지 확인한다.
- 최종 검사기가 저장 전 inputs·outputs·bindings만 다시 검사하고, 같은 STEP의 수정 한도를 공유하는지 확인한다. 전체 IR의 task metadata·순서·depends_on·Assertion·unresolved·final_outputs 일관성 검사는 이 적용 모드 게이트에서 수행하지 않는다.
- 선행 출력 보완은 임시 상태에서 Binding 검사에 반영하고, 검사 통과 후 확정되는지 확인한다. 변경이 있으면 후속 Binding만 같은 검증 범위와 수정 한도 안에서 재검사한다.
- 검사 통과 후 확인용 LLM 호출이 없고, 최종 오류가 남으면 새 성공 IR 파일을 저장하지 않는지 확인한다. 승인본·기존 파일·JSONL·이미 수신한 로그는 보존해야 한다.
- 성공 IR에 generation.execution_mode·generation.policy·모드별 validation이 기록되고 기존 generation.mode/config와 StepMappingResult는 유지되는지 확인한다. 필수값·Assertion 생성·API 실행·사용자 질문은 두 모드 모두 제외되어야 한다.
- UI의 기존 STEP 조건·API·대체 파라미터·XML, 공통 요청/응답 Beautify 탭, 최하단 IR Beautify·로그 다운로드를 유지하고 검사·재시도·중단 행이 실제 상태를 표시하는지 확인한다.

### 11.4 작업 완료 기준

로컬 서버의 승인 또는 승인본 선택 후 고정 STEP별 매핑 후보를 생성하고, 백엔드가 Baseline과 비교한 IR 초안을 저장·미리보기까지 연결해야 한다. 모델은 KB를 기본 사용하고 나머지 자료는 필요할 때 조회한다. 네 도구 전체 호출을 STEP 완료 조건으로 사용하지 않는다.

기존 IR의 scenario_id·version·created_at·sources·tasks[].steps[]·final_outputs와 StepMappingResult의 필드 구조를 유지한다. 입력은 조건에 해당하는 후보만 작성하고 백엔드 비교 정보를 부여한다. 두 모드 모두 assertions=[]·needs_input 분석 상태와 기존 숫자 설정을 유지한다.

확인용 등록 화면의 '중지조건·재시도' 체크박스로 기본 모드/정지·재시도 적용 모드를 고른다 (최종 등록 화면은 늘 적용 모드). 기본 모드는 기존 동작을 유지한다. 적용 모드는 inputs·outputs·bindings 검사, 통신 재시도 1회, STEP 수정 1회와 동일 범위의 최종 재검사를 수행한다. 업무 의존성 충족, Assertion, 미해결 객체 및 전체 IR 조립 검증은 이 매핑 검증 범위에서 제외한다. 검증 통과는 실제 모델의 의미적 정확성이나 업무 API 실행 성공을 증명하지 않는다.


## 실제 구현 연결

- `agent/config.py`: 기본 모드·허용 모드·MODE_POLICIES 및 요청별 설정 사본. 생성 옵션(`stop_retry` → 모드) 정규화.
- `agent/runtime.py`: 모드별 완료 게이트, STEP 수정 한도·세션 보존, 무진전 중단, 최종 오류의 STEP 수정 재개.
- `agent/llm_retry.py`: 하네스의 통신 재시도·Retry-After 처리. SDK 재시도는 0으로 유지.
- `agent/mapping_validation.py`: 합의된 inputs·outputs·bindings 검사항목과 근거 대조. 기존 ParameterTools.validate 진입점에서 호출.
- `agent/tool_registry.py`: 공통 자료 확보와 적용 모드 검사를 연결. 앞 STEP 출력 보완은 Binding 검사 통과 후에만 확정.
- `ir/draft_validate.py`, `ir/draft_build.py`: inputs·outputs·bindings 최종 재검사, STEP 수정 한도 공유, 통과 후 저장.
- `ui/serve.py`, `web/scenario-ir-draft.js`(확인용) · `web/scenario-register.js`(최종 등록): 옵션 기본값·선택·요청 전달, 검사·재시도·중단 로그 표시. 기존 STEP 상세·XML·Beautify·JSONL 유지.

위 src 경로는 src/tap 하위이며 실제 근거 대조 함수의 값 일치 정책은 이번 변경에서 확장하지 않는다. 최종 참조 오류가 선행 출력의 매핑 오류에서 파생된 경우에는 원인 STEP의 수정 대상으로 분류하고, 독립적인 백엔드 조립 오류와 구분한다.
