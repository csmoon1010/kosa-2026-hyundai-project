# API 선택 결과 불러오기 데모

문혜정 담당의 파라미터 매핑 단계에 전달할 **API 선택 결과 JSON**을 시나리오 등록 화면에서 확인한다.

## 실행

WSL 터미널에서 저장소 루트 기준:

```bash
cd hyejung/mini_project_2_demo
# 처음 실행할 때 Python 환경에 패키지가 없으면 설치
python -m pip install -r requirements.txt
PYTHONPATH=src python -m tap.cli serve
```

PowerShell에서는 같은 폴더에서 다음과 같이 실행한다.

```powershell
$env:PYTHONPATH = "src"
python -m tap.cli serve
```

Python 실행 파일은 패키지를 설치한 환경의 것을 사용한다.
브라우저에서 http://127.0.0.1:8765/ 에 접속한다.

## 제공된 예시 불러오기

1. 시나리오 등록 화면의 **설치상품 50,000원 예시 불러오기**를 누른다.
2. 원본 요청, PD → OD → DS 업무 그룹, 8개 단계의 API 후보·선택 결과·선택 이유를 확인한다.
3. **미해결 항목 2개**와 **불러온 JSON 원본 보기**를 확인한다.

예시 파일: [prototype/examples/api-selection-installation-product.json](prototype/examples/api-selection-installation-product.json)

사용자가 제시한 JSON을 그대로 저장했다. status는 `검토 필요`, 출고 지시는 `보류`, 배송 API 3개는 `가선택`이다.
파일을 불러와도 이 상태를 자동으로 승인·확정하지 않는다.

## 추가 예시 불러오기

1. 예시 JSON 파일을 복사해서 원하는 이름(예: `api-selection-order.json`)으로 저장한다.
2. 아래 형식을 유지하면서 원본 요청과 API 선택 결과를 바꾼다.
3. 화면의 **API 선택 결과 불러오기**에서 새 파일을 선택한다. 파일을 저장하는 위치는 자유이며, 예시 버튼이나 소스 코드를 수정할 필요가 없다.
4. 불러온 파일은 업무 번호 `path_sequence`, 단계 번호 `step` 순서로 표시된다.

최소 예시:

```json
{
  "original_question": "승인된 상품으로 주문을 만들어줘",
  "status": "API 선택 완료",
  "api_selection_results": [
    {
      "path_sequence": 1,
      "step": 1,
      "domain": "OD",
      "edge": "주문 생성",
      "api_candidates": ["DEMO_OD_CREATE_PAID_ORDER"],
      "selected_api_id": "DEMO_OD_CREATE_PAID_ORDER",
      "selection_status": "선택",
      "selection_reason": "승인된 상품으로 결제완료 주문을 만드는 API이다."
    }
  ],
  "unresolved": []
}
```

- 파일은 UTF-8 JSON, 최대 2MB로 저장한다. UTF-8 BOM이 있어도 불러올 수 있다.
- `original_question`, `status`, `api_selection_results`는 필수다.
- 각 결과에는 `path_sequence`, `step`, `domain`, `edge`, `api_candidates`, `selected_api_id`, `selection_status`, `selection_reason`를 넣는다.
- `path_sequence`와 `step`은 1 이상의 정수다. 두 번호의 조합은 중복되지 않아야 하며, 같은 업무 번호의 도메인은 같아야 한다.
- 선택된 API는 `api_candidates`에 포함되어야 한다. 미선택이면 `selected_api_id`에 문자열 `"null"`이 아닌 JSON `null`을 넣는다.
- `선택`·`승인`·`선택 완료` 상태에는 선택된 API ID가 있어야 한다. 보류·가선택도 입력할 수 있다.
- `unresolved`는 생략하거나 빈 배열로 둘 수 있다. 항목을 넣으면 `path_sequence`, `step`, `reason`을 적는다. 업무 전체의 문제는 `step: null`로 적는다.
- PD는 상품, OD는 주문, DS는 물류로 표시된다. 다른 도메인은 파일에 적은 코드로 표시된다.
- `DEMO_*` API가 현재 API Catalog에 없더라도 입력 파일의 선택 결과를 확인할 수 있다. 실 API 호출·Catalog 등록은 하지 않는다.
- 추가 필드는 그대로 보존하며 **JSON 원본 보기**에도 표시한다.

## 불러온 결과의 범위

이 기능은 API 선택 결과를 읽어 검토하는 단계다. 파일은 브라우저에서 읽고 화면의 초안에 유지하며 서버에 업로드하거나 저장하지 않는다.
새로고침하거나 다른 메뉴로 이동해 초안이 닫히면 다시 불러온다. 원본 JSON 파일은 그대로 남는다.

파라미터 매핑, Output Binding 생성, Scenario IR 생성·검증·최종 등록은 후속 구현이다.
불러온 자료를 기존 단일 그래프 계획으로 다시 계산하지 않도록, 이 초안에서는 기존 **시나리오 생성** 버튼을 숨긴다.
기존 자연어 요청 생성은 **＋ 새 시나리오 등록**을 눌러 사용할 수 있다.

HTML을 파일로 직접 열어도 파일 선택으로 불러올 수 있다. 제공 예시 버튼은 HTTP 서버 접속이 필요하다.

## 파일 구성과 확인

- `prototype/offline-ui.html`: 파일 선택과 제공 예시 버튼 연결.
- `prototype/api-selection-import.js`: 입력 검증, 파일 읽기, 업무별 표시.
- `prototype/api-selection-import.css`: 불러오기 화면 스타일.
- `prototype/examples/api-selection-installation-product.json`: 사용자 제공 예시.
- `tests/api-selection-import.test.cjs`: 입력 형식·참조 무결성 검증.

Node.js가 있으면 별도 패키지 설치 없이 다음 검증을 실행할 수 있다.

```bash
node --test tests/api-selection-import.test.cjs
```


## 전처리 JSON 연결

Canonical Schema, Parameter KB, Baseline, Response Outputs는 이웃 폴더
`data/out/parameters/`의 JSON을 읽는다. 실행 중 SQLite를 열거나 노트북을 실행하지 않는다.
JSON 내부의 `document_id`(Canonical은 `documentId`)와 `api_id`(`apiId`)를 `:`로 결합해
승인 결과의 `selected_api_id`와 연결하며, 파일명의 해시는 조회 키로 사용하지 않는다.

- `canonical_schema/`: 전체 요청 경로, XML 경로, 타입, 필수 여부를 보존한다.
- `parameter_kb/api/`, `parameter_kb/common/`: Canonical 기본 지식과 VERIFIED 지식만 사용한다.
- `response_outputs/`: 활성 SUCCESS 정의에 속한 enabled 필드 중 재검토가 필요 없는 필드만 사용한다.
  성공 스키마와 경로, 불일치 시 stop 정책을 전달한다. 실제 응답 판정은 향후 실행기에 연결한다.
- `baseline/`: example 초안을 기본 표시하고 사용자 등록 여부를 구분한다.
  화면의 등록값은 `data/baselines/preprocessing/`에 JSON으로 보관하여 산출물 재생성 시 보존한다.
  편집 키는 필드 이름이 아닌 전체 `parameter_path`이며, null은 미해결 값으로 유지한다.
  등록 검증은 경로·타입·enum을 확인하며 실제 API 호출 성공을 검증하지 않는다.

노트북에서 산출물을 생성한 뒤, 서버 화면 상단의 **전처리 산출물 갱신**을 누른다.
갱신은 JSON을 다시 읽고 `prototype/tap-data.js`도 갱신한다. 서버 소스 변경을 반영하려면
실행 중인 `tap.cli serve`를 재시작한다. 정적 화면의 번들만 갱신할 때는
`PYTHONPATH=src python -m tap.cli ui-data`를 실행한다.

## 승인 후 Scenario IR 초안 생성

로컬 서버의 실행 환경에 `OPENAI_API_KEY`, `OPENAI_DEFAULT_MODEL`을 설정한다. `.env`를 사용해도 된다. 키 값은 화면에 입력하지 않는다.

시나리오 등록에서 의도분석·API 선택 파일을 불러온 뒤 **승인**하면 저장된 승인본으로 IR을 자동 생성한다. 등록 영역의 **IR 초안 생성** 카드에서 호출 횟수·누적 토큰·생성 시간·출력 토큰을 조정하거나, 저장된 승인본을 선택해 **IR 다시 생성**할 수 있다.

결과는 `data/out/scenario_ir_drafts/<scenario_id>-v1.json`에 저장한다. 화면 상단의 STEP 목록에서 단계를 선택하면 업무 조건·API·대체 파라미터·Baseline XML을 표시한다. 생성 과정·로그와 최하단의 전체 IR JSON Beautify를 제공한다. 부족한 정보는 `needs_input`으로 보존한다. 생성 실패 시 승인 파일은 유지되므로 재생성만 하면 된다.

이 기능은 실제 업무 API를 호출하거나 실행용 시나리오를 등록하지 않는다. 입력의 기존 미해결 항목은 보수적으로 보존한다. 자동으로 적용할 수 없는 업무 규칙은 미해결로 남긴다.

구현: `src/tap/agent/runtime.py`(하네스 코어), `config.py`(기본값·설정 검증·서버 CONFIG·오류 문구), `tool_registry.py`(도구 스키마·실행 연결), `parameter_tools.py`(자료 조회·도메인 검증), `prompts.py`(프롬프트), `src/tap/ir/draft_build.py`(고정 계획·초안 조립·저장), `prototype/scenario-ir-draft.js`(설정·미리보기).

화면은 `generation_options`에 중지조건·재시도, 압축 1, 압축 2, 승인게이트, 인젝션 대응을 전달한다. 인젝션 대응은 중지조건·재시도와 승인게이트가 모두 선택됐을 때만 사용할 수 있다. 모두 해제하면 기존 `basic` 동작을 유지한다. 이전 `generation_mode=basic/validated` API 요청도 지원한다. 서버는 `config.configuration()`으로 검증하고 Runtime은 `harness_configuration()`으로 독립적인 CONFIG 사본을 사용한다. 프롬프트·오류 문구·모델 연결 옵션은 서버 설정으로 유지하며 IR의 `generation.config`에는 숫자 설정만 기록한다. Python 코드 변경 후에는 로컬 서버를 재시작해야 한다.

생성 중에는 **생성 과정 · LLM / TOOL 로그**에서 전체·단계별 턴, 토큰 사용량, 경과 시간, 실제 LLM 프롬프트·출력, 선택된 도구와 호출 결과를 볼 수 있다. 상세 항목을 펼쳐 내용을 확인한다. 토큰은 응답 완료 시 갱신되며 실패한 경우에도 받은 로그는 남는다. 이 화면은 모델이 반환한 도구 선택을 표시하며 비공개 내부 추론을 표시하지 않는다.

화면은 기존 생성 API에 `Accept: application/x-ndjson`을 보내 실시간 이벤트를 받는다. 헤더 없이 호출하면 기존 JSON 응답을 유지한다. `agent/progress.py`는 표시용 인증값을 마스킹하며, 상세 진행 로그는 요청별 JSONL 파일에도 즉시 저장한다. 서버 재시작과 브라우저 강력 새로고침 후 적용된다.

IR 생성은 KB(schema 포함)를 기본 조회하고, 기존 설정 해석에 Baseline이 필요하거나 새 응답 필드 정의에 Response Outputs가 필요할 때만 추가 조회합니다. StepMappingResult를 받은 백엔드가 Baseline과 비교해 변경 여부를 표시하며, 비교 확정을 위한 LLM 재호출은 하지 않습니다. 기본 모드에서는 매핑 검증을 비활성화하고, 정지·재시도 적용 모드에서는 inputs·outputs·bindings에 직접 관련된 항목만 검증합니다. 필수값 완성 검사는 하지 않습니다.

IR 생성·결과 카드는 승인 버튼이 있는 편집 그리드 아래에 별도 전체 너비로 표시한다. 진행 표는 LLM 턴별 행과 도구 호출별 행으로 요청·응답·STEP·시간·토큰을 보여주며, `validate_mapping`의 `valid`는 별도 컬럼에 true/false로 표시한다.

전체 에이전트 로그는 `data/out/scenario_ir_logs/IRRUN-<시각>-<고유ID>.jsonl`에 저장한다. LLM 입력·출력, 도구 인자·결과·valid, 턴·토큰·시간, 최종 검증과 성공/실패 기록을 포함한다. 이벤트마다 flush하므로 예산 초과나 생성 실패 시에도 앞선 로그가 남는다. 인증값은 표시 로그와 같은 방식으로 마스킹한다.

화면의 **전체 로그 · JSONL 다운로드** 링크는 생성 시작부터 표시된다. 성공 응답의 `log_file`·`log_url`, IR의 `generation.log_file`로도 확인할 수 있다. 파일을 줄 단위로 JSON 파싱하면 생성 과정을 순서대로 재구성할 수 있다. 페이지 최하단에는 저장된 전체 JSONL 실행 이력 표가 최초 진입 시부터 표시되며, 옵션·실행 시각·수행 시간·모델 호출·턴·입출력/임베딩/총 토큰과 로그 다운로드 링크를 확인할 수 있다. 생성 옵션 체크박스의 조합과 시작일·종료일을 함께 지정해 필터링할 수 있다. 옵션 조합 제한을 켜면 체크 상태와 정확히 일치하는 실행만 남긴다. 새 실행 완료 후에도 표를 갱신한다.

로그 표에서 행을 클릭하면 표 아래 **공통 상세 영역**에 해당 항목을 표시한다. **요청 프롬프트 / 인자**, **응답 결과** 탭을 전환해 2칸 들여쓰기 JSON Beautify와 구문 강조로 확인할 수 있다. 표에는 요청·응답 컬럼을 두지 않는다. 선택한 행의 실시간 응답이 도착하면 상세도 갱신되며, 전체 JSONL 저장·다운로드 기능은 유지된다.

기존 중지조건·재시도·압축 1·압축 2의 8가지 조합을 유지한다. 승인게이트·인젝션 대응을 포함하면 의존 관계를 만족하는 20가지 조합을 지원한다. 실행 정책은 중지조건·재시도 선택에 따라 기존 basic/validated로 기록한다. 두 모드 모두 모델 도구는 조회 3개이며 `validate_mapping`은 백엔드 전용이다. 적용 모드의 단계별·최종 검증은 파라미터 경로·값·근거, 출력 정의, Binding 연결의 합의된 검사만 수행한다. STEP/API 식별, Assertion, 업무 의존성 완전성, unresolved 객체는 해당 매핑 검증의 실패 조건이 아니다. 원본 Baseline은 변경하지 않는다. 결과의 `generation.execution_mode`, `generation.policy`, `generation.validation`에서 모드와 검증 실행 상태를 확인할 수 있다.

### IR 에이전트 Responses API 하네스

`src/tap/agent/runtime.py`는 강의 `5. harness_core.ipynb`처럼 `client.responses.create()`를 사용합니다. `config.py`의 instructions를 별도 전달하고, 응답의 function_call을 모아 실행한 뒤 전체 output 항목과 function_call_output을 다음 호출 입력에 추가합니다. store=False이며 STEP별 대화는 새로 시작하고, 예산은 전체 요청에서 집계합니다.

Structured Outputs는 `output_models.py`의 Pydantic 스키마를 `text.format`에 전달하며, 최종 output_text는 같은 모델로 파싱합니다. KB 기본 조회와 필요한 조건부 자료 확보를 확인하며, 백엔드가 매핑 후보를 Baseline과 비교합니다. 실시간 로그의 요청 상세에는 instructions/input/tools/text를, 응답 상세에는 Responses 원본과 status를 표시합니다.

SDK는 `openai>=1.68.2`가 필요합니다. 기존 환경에서는 requirements를 다시 설치하고 로컬 서버를 재시작하세요.

### KB 기본 조회와 조건부 조회

모델 도구는 get_parameter_knowledge·get_baseline_request·get_response_outputs의 3개입니다. 각 STEP의 첫 호출은 KB를 지정하고, 그 뒤 tool_choice=auto로 필요한 도구를 선택합니다. KB는 schema와 원본 기술 정보의 출처를 함께 반환합니다. Canonical은 백엔드의 기술 정보 보완·IR API 구성에만 사용합니다. 적용 모드에서 백엔드 매핑 검증은 합의된 inputs·outputs·bindings 항목으로 한정합니다.

Baseline을 모델이 조회하지 않아도 백엔드는 비교를 수행합니다. replace·unchanged·response_binding·input_needed·comparison_unavailable을 구분하고 baseline_present·comparison_reason으로 비교 불가를 표시합니다. 화면의 백엔드 Canonical·자료 확인·Baseline 비교 행은 모델 턴·토큰으로 집계하지 않으며, 공통 요청/응답 상세 탭과 JSONL에도 기록합니다. STEP 간 조회 캐시는 추가하지 않았습니다.

### 조회 결과 의존성과 출력 보완

고정 STEP은 후속 업무의 intent_task.conditions와 input_dependencies/output_consumers를 전달합니다. 명시적인 업무 결과 참조와 출처가 하나인 조회 결과 참조를 연결하며, 모호한 출처를 임의로 선택하지 않습니다.

승인 계획상 필요한 응답 자료는 Response Outputs로 확보합니다. 기본 모드는 기존의 의존성 보완 피드백을 유지합니다. 적용 모드의 매핑 검증은 조회한 자료가 실제 outputs·bindings 후보와 일치하는지 확인하지만, 모든 업무 의존성이 후보에 반영됐는지 또는 unresolved.dependency_ids가 완전한지는 검사하지 않습니다. 기존 출력이 충분한 Binding에는 추가 응답 조회를 강제하지 않습니다.

앞 STEP 출력이 누락됐더라도 조회한 응답 메타데이터와 일치하는 Binding을 제안하면 백엔드가 그 출력 정의만 보완합니다. 앞 STEP 입력·업무 순서·API는 바꾸지 않습니다. 보완 결과는 화면의 “앞 STEP 출력 보완 · 백엔드” 행과 JSONL에 기록합니다. 필수값 완성·실제 API 실행은 제외합니다.

### STEP 상세와 XML 미리보기

IR 결과 영역은 왼쪽 STEP 목록과 오른쪽 상세이며 좁은 화면에서는 위아래로 배치됩니다. 업무 조건은 STEP 상세에 통합했고 하단 업무/단계·매핑 후보 비교 표와 나머지 개별 결과 표는 제거했습니다. 원본 IR의 데이터는 최하단 IR JSON Beautify에 모두 남습니다.

XML 미리보기는 `src/tap/ir/xml_preview.py`에서 원본 Baseline을 복사해 만듭니다. 고정값과 출력 참조를 구분하며 {{…}}는 미리보기용 표기입니다. 원본 파일이나 실제 요청을 변경하지 않습니다. 생성 응답의 step_previews와 실시간 step_preview 이벤트로 전달하며 LLM 입력과 저장 IR에는 추가하지 않습니다. 기존 화면 설정·로그 상세 탭·JSONL 다운로드는 유지합니다. 서버 재시작과 화면 새로고침 후 적용됩니다.


## 정지·재시도 적용 모드

IR 생성 설정의 **중지조건·재시도** 체크박스로 기존 validated 정책을 선택한다. **압축 1**, **압축 2**와 독립적으로 조합할 수 있다. 초기 선택과 기본값 복원은 모두 해제다. 생성 중에는 옵션이 고정되며 승인 직후 자동 생성·승인본 재생성 모두 같은 선택값을 사용한다.

적용 모드는 제출 후보·출력·Binding·업무 의존성을 백엔드에서 검사한다. 일시 LLM 통신 오류는 논리적 요청별 추가 1회, 매핑 오류는 STEP별 수정 1회만 허용한다. 429 대기 시간이 있으면 이를 따르고, 인증·요청·비일시 한도 오류는 재시도하지 않는다. SDK 자동 재시도는 꺼서 중복 시도를 막는다. 오류 분류는 [OpenAI 공식 오류 안내](https://developers.openai.com/api/docs/guides/error-codes)를 참고한다.

업무 정보 부족은 유효한 미해결로 보존하고, 수정 뒤에도 오류가 남거나 필요한 자료가 손상되면 중단한다. 저장 전 최종 IR 검사에서 매핑 오류는 해당 STEP의 남은 수정 기회만 사용하고, 백엔드 조립 오류는 중단한다. 선행 출력 수정 후에는 후속 참조도 재검사한다. 검증 통과 후 확인용 LLM 호출은 하지 않는다.

- 정책·기본값: `src/tap/agent/config.py`
- 하네스·STEP 수정 상태: `src/tap/agent/runtime.py`
- 통신 재시도: `src/tap/agent/llm_retry.py`
- 후보 검사: `src/tap/agent/mapping_validation.py` (`ParameterTools.validate()` 진입점)
- 최종 검사·저장 게이트: `src/tap/ir/draft_validate.py`, `draft_build.py`

로그에서 백엔드 검사의 valid·오류, 통신 시도·대기·재시도, 수정 요청·중단 사유를 확인할 수 있다. 행 선택 후 요청/응답 JSON Beautify와 JSONL 다운로드는 유지한다. 선택 모드·정책은 IR의 `generation.execution_mode/policy`에 기록하며 기존 `generation.mode=baseline_replacements`와 숫자 설정은 유지한다.

두 모드 모두 필수값 검사·Assertion 생성·업무 API 실행·사용자 질문은 제외하고 `needs_input` 분석용 초안을 저장한다. 별도 근거 값 일치 구체화 정책은 추가하지 않았다. 서버를 재시작하고 브라우저를 강력 새로고침하면 체크박스 옵션을 사용할 수 있다.


## 독립 생성 옵션과 컨텍스트 압축

- **중지조건·재시도**: 기존 validated의 매핑 검사·통신 재시도·STEP 수정 한도를 적용한다. 해제해도 기존 전체 생성 예산은 유지한다.
- **압축 1**: `data/out/parameters/parameter_vectors/`의 기존 Chroma 컬렉션을 읽고, 선택된 API 안에서 조건·original_question·현재 STEP selection_reason의 세 질의 범주를 top-k=5 검색한다. 명시적인 의존성이 있으면 그 관계를 우선 활용하고, 관계가 없거나 ambiguous이면 같은 첫 KB tool call에서 LLM이 다른 STEP의 관련도를 판정한다. 0.7 이상인 후보의 업무 조건만 현재 조건 질의에 합치며, 별도 LLM 호출이나 STEP별 추가 질의는 없다. 동일 질의와 후보 parameter_path는 중복 제거하며 질의 출처·선택 STEP·점수를 로그에 남긴다. `config.CONFIG['kb_top_k']`는 1~10으로 설정할 수 있다. query에는 기존 인덱스와 같은 `text-embedding-3-small`을 사용한다. 범위 확대는 k=10, 지정 경로 상세 조회, 전체 API KB 조회를 지원한다. 인덱스 부재·불일치·검색 오류는 이유를 로그에 남기고 전체 KB로 전환한다. 새 컬렉션 생성·원본 동기화는 생성 중 수행하지 않는다.
- **압축 2**: 선행 STEP의 관련 출력 정의와 후속 소비 조건만 선별한다. 관계나 필드가 불확실하면 출력 정의 범위를 넓힌다. 검색은 기존 업무조건·original_question·승인된 현재 STEP의 `selection_reason`을 사용하며, LLM이 연결 검색어를 새로 만들지는 않는다. 검색 뒤 KB 응답에 별도 연결 문맥을 추가하지 않는다. LLM은 기존 단계 문맥과 조회된 ParameterKB로 Binding을 작성하고, 백엔드는 source/output 존재, 현재 API 입력 경로와 타입 호환성을 검증한다. 전체 원본과 JSON Pointer는 검증·조립용으로 보존하며 최종 수정 시에도 최신 상태로 선별한다.

구조화 조건은 `conditions: [{"search_query":"상품 가격","value":50000,"unit":"원"}]` 형식을 사용할 수 있다. 문자열 conditions도 단일 질의로 지원한다. 원래 값·단위는 모델 입력에 유지하며 조건 분리용 LLM 호출은 추가하지 않는다. 명시적 관계는 조건의 source_task_sequence/source_step_id와 선택적 source_output_names로 전달할 수 있다. 값이 없는 관계를 임의 확정하지 않는다.

```json
{"generation_options":{"stop_retry":true,"kb_rag":true,"dependency_projection":true}}
```

선택 결과는 IR의 `generation.options`와 시작 로그에 기록한다. `generation.config`의 숫자 설정 4개는 유지한다. 압축 1의 KB 도구는 scope=search/expand/paths/full과 parameter_paths를 사용하며, 두 압축이 꺼져 있으면 기존 도구 계약과 입력 구조를 유지한다. 임베딩 토큰·호출·시간과 cached_tokens도 사용량에 기록하고 생성 한도에 반영한다. 가격은 저장된 실제 토큰과 사용하는 모델의 단가로 별도 계산한다.

작업계획: `scenario_ir_context_compression_plan.md`
검증 결과와 미실행 범위: `scenario_ir_context_compression_verification.md`

Python 검증은 `PYTHONPATH=src python -m pytest -q tests`로 실행한다. `scripts/evaluate_kb_top_k.py`와 `scripts/evaluate_context_compression.py`는 별도의 실제 API 호출을 사용하는 평가 도구다. 현재 자동 테스트와 실제 검색 평가는 완료했으며, 실제 모델의 24회 반복 비교는 자동 승인 검토에서 차단되어 실행하지 않았다. 따라서 k=3의 검색 재현율이 좋아도 기본 k는 아직 5로 유지한다.


## STEP 수 기반 생성 예산 (2026-11-02)

승인본을 로드하면 서버가 STEP 수로 예산을 계산해 읽기 전용으로 표시합니다.
LLM 호출은 `min(40, STEP 수 × 5 + 2)`, 토큰은 `min(400000, STEP 수 × 50000 + 30000)`, 시간은 `min(600, STEP 수 × 60 + 30)`입니다. 호출당 출력은 4,096토큰입니다.
각 STEP은 기본 호출 5회를 가지며 6번째부터 공통 예비 2회에서 차감합니다. 다른 STEP의 미사용 기본 호출은 이전하지 않습니다. 절대 상한은 예비보다 우선합니다.
실패·타임아웃·통신 재시도도 실제 전송 시도마다 호출 1회를 소비합니다. 임베딩 호출은 LLM 횟수에서 제외하고 토큰·시간에는 포함합니다. 캐시 토큰은 입력에 포함된 값으로 중복 합산하지 않습니다.
예산은 실시간 이벤트, JSONL, 생성 결과의 budget/budget_usage 및 하단 누적 실행 기록의 사용량/한도에서 확인합니다. 기존 로그의 한도가 없으면 —로 표시합니다. 기존 generation_config 명시 API 요청은 legacy_fixed_v1로 구분합니다.
입력 토큰 사전 검사는 UTF-8 바이트 수와 여유분으로 보수적으로 추정하므로 실제 토큰보다 일찍 중단될 수 있습니다. 통신 오류의 미확인 토큰은 usage_unknown_attempts로 구분합니다. 로컬 작업의 시간 초과는 작업 완료 후 감지할 수 있습니다.


## 승인게이트와 인젝션 대응 옵션

서버 재시작과 브라우저 강력 새로고침 후 적용된다. 모든 옵션의 초기값과 **옵션 기본값 복원**은 OFF다.

- **승인게이트:** 매핑 검증·압축 옵션과 독립적으로 선택한다. 생성 완료 후 **승인게이트 · 입력 결정** 영역에서 지금 입력 / 실행 시 입력 / 검토 보류를 선택하고 **검토 저장**한다. 보류가 없으면 **결정본 확정**이 가능하다. 값만 결정할 때 LLM을 다시 호출하지 않는다.
- **인젝션 대응:** **중지조건·재시도 + 승인게이트**가 모두 ON일 때만 선택 가능하다. 선행 옵션을 끄면 자동 해제·비활성화되며, 다시 켜도 자동 선택하지 않는다. 서버도 잘못된 조합을 거부한다.
- 인젝션 ON은 프롬프트에 자료 속 역할 변경·검증 생략·승인 사칭을 따르지 않도록 명시하고 도구 결과를 material/notice로 구분한다. OFF에서도 별도로 켜진 기존 매핑 검증·승인게이트는 동작한다. 새로운 예시값 확정 정책이나 탐지 모델은 추가하지 않는다.

검토 상태는 `data/out/scenario_ir_reviews/<scenario_id>.json`에 저장한다. 새로고침 후 **저장된 검토 초안 → 검토 불러오기**로 이어간다. 생성 시 저장한 옵션이 해당 초안에 적용되며, 화면 체크 상태를 바꿔도 기존 검토를 우회하지 않는다. 원본 v1과 Baseline은 보존하고 사용자 결정은 새 버전 IR에 저장한다. legacy `status=needs_input`은 유지하며 `review.status`가 검토/확정 상태를 나타낸다.

실행 시 입력은 `runtime_inputs` 정의만 저장하며 실제 값은 null로 남긴다. 출처·의미·관계가 모호하거나 배열·복합 입력인 항목은 보류해 원본 검토로 돌린다. 선행 입력 변경으로 후속 고정값 재검토가 필요한 경우에도 확정을 막는다. 승인본·자료·원본 초안이 바뀌면 다시 생성해야 하며, 오래된 revision·동시 제출·중복 제출을 처리한다. 미저장 변경이 있으면 먼저 검토 저장해야 한다. 확정은 입력 결정을 확인하는 단계이며 실제 업무 API를 실행하지 않는다.

검토 API:

- `GET /api/scenario-ir-reviews`: 저장된 검토 목록
- `GET /api/scenario-ir-reviews/{scenario_id}`: 현재 결정·revision·미리보기
- `POST /api/scenario-ir-reviews/{scenario_id}/decisions`: `{expected_revision, decisions:[{target_id, choice:"now"|"runtime"|"hold", value?}]}`
- `POST /api/scenario-ir-reviews/{scenario_id}/confirm`: `{expected_revision}`

값은 서버가 지정한 target_id로만 적용한다. now에만 타입이 맞는 value를 전달한다. 위조 status·임의 경로 같은 필드는 거부하며 버전·자료 충돌은 HTTP 409다. 승인 이벤트는 기존 실행 JSONL에도 남기되 사용자 입력값을 이벤트에 중복 기록하지 않는다.

검증:

```bash
PYTHONPATH=src python -m pytest -q tests
```

새 테스트는 옵션 의존 관계, UI 조작·재불러오기, 원본 보존, 사용자 근거·XML 갱신, 동시성·오래된 자료, 승인 위조 및 스텁 모델의 규칙 무시 후보 차단을 확인한다. 이는 실제 모델의 인젝션 저항성 측정과 구분한다. 실제 모델 OFF/ON 비교 실험은 다음 명령으로 별도 실행할 수 있다(모델 환경 설정 필요, 호출 비용 발생). 원본을 보존한 임시 복사본의 첫 승인 STEP을 대상으로 각 케이스를 기본 3회 반복하며 결과와 로그를 evaluation에 보관한다.

```bash
PYTHONPATH=src python scripts/evaluate_injection.py --live --approved api-selection-approved-order-shipment.json
```
