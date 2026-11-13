# 구조

자연어 요청 하나가 등록 시나리오가 되고, 실행되기까지의 흐름입니다.

```
[사전 작업 — 명세가 바뀔 때만]
명세(OpenAPI) ─build→ API Catalog · Metadata · Tool Registry          src/tap/spec · catalog · registry
전처리(혜정)  ──────→ Canonical Schema · Parameter KB · Baseline · Response Outputs · 벡터 인덱스   data/out/parameters
사람          ──────→ 상태 그래프(data/graphs) · 보정 규칙(overrides · rules.ui)

[시나리오 등록 — 요청마다]
자연어 ─①→ 업무 목록 ─②→ 업무별 경로 ─③→ 단계별 API ─게이트→ 권한 등급 · 확인할 단계
       ─검토 초안→ Scenario IR(입력값 · 결과 넘기기) ─승인→ 등록 시나리오

[실행]
등록 시나리오 ─실행 확인(승인 · 해시 · R2)→ 드라이런 → 실행 이력
```

## 사전 작업

| 산출물 (`data/out/`) | 내용 | 누가 쓰나 |
|---|---|---|
| `api_operations.json` | 명세 파싱 결과 — API별 요청/응답 필드(한글 이름 · 타입 · 예시) | 전처리 · ③ · 화면 |
| `api_metadata.json` | API별 쓰기/조회 · 동작 · 별칭 · **구분값(selectors)** · 되돌림 불가 · 구별 메모 | ③ · 게이트 |
| `api_catalog.json` | 후보로 쓸 수 있는 API 목록 (사용 여부, 내용이 바뀔 때만 버전 증가) | ③ · 재승인 판단 |
| `tool_registry.json` | 도메인별 연결 설정(주소 환경변수 · timeout · 인증 헤더 이름) | 실행기(연결 예정) |
| `parameters/` | Canonical Schema · Parameter KB · Baseline · Response Outputs · 벡터 인덱스 | IR 생성 |

- **구분값**: 한 API 가 여러 일을 할 때 이번 일을 고르는 요청 필드와 값 (예: `multiOshpProcess` 의 `procGb` P1 출고진행 · P2 출고완료 · P3 배송완료).
- **보정**: 개발 담당자는 `data/config/overrides.yaml`, 화면에서 넣은 규칙은 `data/config/rules.ui.yaml` — 빌드할 때 명세 위에 합친다.
- **상태 그래프**: 그래프 하나 = 공통코드의 상태 코드 그룹 하나. 상태(노드)와 화살표(업무 이름)만 갖고, API 는 적지 않는다 — API 는 ③ 이 Metadata 에서 찾는다. 관리자 메뉴에서 그려 `data/graphs/<코드그룹ID>.yaml` 로 저장한다.

## ① 요청 이해 — `goal/extract.py`

LLM(Structured Output)이 요청을 업무 목록(TaskPlan)으로 나눈다.

| 칸 | 뜻 |
|---|---|
| `domain` | 업무 도메인 (목록 안에서만) |
| `origin` | 신규(새로 만듦) / 기존(있는 데이터를 찾아 바꿈) |
| `action` · `conditions` | 업무 이름 · 설명 문장 |
| `count` | 건수 (말하지 않으면 1) |
| `constraints` | 이름 · 값 · 역할(대상조건 = 찾을 조건 / 설정값 = 넣을 값) |
| `depends_on` | 앞 업무 결과를 쓰는지 |
| `source_phrases` | 근거 구절 — 요청 원문에 없으면 환각으로 보고 거절 |

- 만든 뒤 값을 고치는 요청("5000원인 상품을 만들고 8000원으로 수정")은 업무 둘(신규 + 기존, `depends_on`)로 나눈다.
- 요청 속 지시문은 LLM 이 적은 것 + 지시문 낱말 + 시스템 식별자(구분값 필드 · API 이름 · 그래프 ID …) + `필드=값` 모양으로 감지 — 하나라도 있으면 ②③ 없이 차단 (`data/config/permissions.yaml`).

## ② 경로 찾기 — `graph/paths.py` · `graph/plan.py`

1. LLM 은 업무마다 그래프 · 출발 상태 · 목표 상태를 **이름으로만** 고른다.
2. 코드가 이름을 코드로 바꾸고 그래프 탐색(BFS)으로 경로를 계산한다. LLM 은 경로를 쓰지 않는다.
3. 출발 데이터를 얻는 방법(`start_by`): 새로 만들기 화살표가 있으면 만들기, 없으면 출발 상태인 데이터를 **조회**로 찾는다(0번 단계).
4. 맞는 그래프가 없는 업무는 '그래프 없음' — ③ 이 업무 이름 · 조건으로 API 를 찾는다.

## ③ API 고르기 — `apis/select.py`

경로의 단계마다 후보를 찾아 점수를 매기고, 확정 검사를 거쳐 고른다 → [api-selection-rule.md](api-selection-rule.md).

- 결과 상태: **선택**(그대로 써도 됨) · **가선택**(사람 확인 필요) · **보류**(고를 API 없음)
- **참조 조회**: 쓰기에 넣을 코드를 이름으로 받았으면("브랜드가 아디다스") 이름 → 코드 조회 단계를 앞에 넣는다.
- **행 상태값**: 요청에 `rowType` · `rowFlag` 가 있으면 업무 동작으로 채운다 (생성 INSERT · I / 수정 UPDATE · U / 삭제 DELETE · D).

## 승인 게이트 — `apis/gate.py`

코드가 정한다. LLM 이나 요청 문장("승인 없이 해")으로 바꿀 수 없다.

| 등급 | 뜻 | 등록 때 | 실행 때 |
|---|---|---|---|
| R0 | 조회 | 자동 | — |
| R1 | 되돌릴 수 있는 쓰기 (그래프에 되돌아가는 화살표 있음) | 시나리오 승인 | — |
| R2 | 되돌릴 수 없는 쓰기 (Metadata 되돌림 불가 · 되돌아가는 화살표 없음 · 그래프 없는 생성/수정) | 시나리오 승인 | **실행할 때마다 확인** |
| R3 | 금지 (1차 범위 밖 도메인 · 삭제류 API) | 차단 | — |

- 사람이 확인하지 않은 선택(가선택 · LLM 이 고른 API)은 그 단계를 등록 때 직접 확인해야 한다.
- 보류 · 경로 없음 · 범위 밖 업무가 있으면 차단 — 승인할 수 없다.
- 승인은 **선택 결과 해시**에 묶인다. 승인 뒤 API 선택이 바뀌면 실행이 거부된다. 등록 뒤 API Catalog 버전이 바뀌면 '재승인 필요'.

## 시나리오 생성 (Scenario IR) — `ir/`

1. **검토 초안** (`ir/handoff.py`): ①②③ 결과를 IR 생성 입력 형식으로 바꾼다 — 단계 번호, 구분값, 앞 단계 결과를 받는 단계(`source_step_id`), 참조 조회, 업무 사이 결과(`depends_on`), 행 상태값. 승인 전이라 `approval_status: review` (`data/ir_inputs/review-*.json`).
2. **IR 생성** (`ir/draft_build.py` · `agent/`, 혜정): 단계마다 에이전트가 요청 스키마 · Parameter KB · Baseline · Response Outputs 를 보고 입력값을 정한다.
   - 입력값 출처: `fixed`(고정값 — 요청 값 · 구분값 · 행 상태값) · `bind`(앞 단계 응답) · `run_input`(실행할 때 받을 값) · `unresolved`(정하지 못함)
   - 생성 옵션: 중지조건 · 재시도(매핑 검증 · 최종 IR 검증 · 재시도, 최종 화면은 늘 켬), 압축 1(조건별 Parameter KB 검색), 압축 2(의존성 기반 단계 문맥 선별)
   - 결과: `data/out/scenario_ir_drafts/SCN-*.json`, 생성 로그 `data/out/scenario_ir_logs/`
3. 설계 · 예산 · 검증 상세는 [scenario-ir.md](scenario-ir.md) 와 `scenario-ir-*.md` 문서.

## 등록 · 실행 — `api/services.py`

- **등록** (`POST /api/register/scenarios`): 검토 초안과 IR 이 이 분석 결과(선택 해시)로 만든 것인지 확인 → 게이트 승인 → 분석 결과 · 게이트 · 승인 · IR 을 한 파일로 고정 (`data/registered/rs-*.json`).
- **실행** (`POST /api/run/dry-run`): 시나리오마다 실행 확인(승인본 · 선택 해시 · 이번 실행에서 확인한 R2 단계, 재승인 필요 여부) → IR 로 단계별 요청을 만든다 — Baseline XML 에 입력값을 덮고, 앞 단계 값은 자리표시. 하나라도 통과하지 못하면 아무것도 남기지 않는다. 결과는 `data/runs/`.
- 실제 API 호출(실행기)은 아직 연결 전이다.

## LLM 호출 관리 — `trace.py` · `data/config/llm.yaml`

- 요청 하나(①②③)의 예산: LLM 호출 6회 · 토큰 60,000 · 180초 · $0.5. 넘으면 다음 호출 전에 멈추고 이유를 남긴다.
- 재시도: 형식 실패 · 통신 오류만 (지수 대기). LLM 거절 · 출력 토큰 한도 · 받은 뒤 검사에서 걸린 것은 다시 묻지 않는다.
- IR 생성 예산은 단계 수에 비례(`agent/budget.py`), 비용 상한 $1.0.
- 호출마다 단계 · 토큰 · 지연 · 비용을 `data/out/traces/` 에 남긴다.

## 서버 API

FastAPI (`src/tap/api/`) — 경로는 메뉴 이름 기준. 요청 · 응답 상세와 작업 기준은 [fastapi.md](fastapi.md), 서버를 띄우면 `/api/docs` 에서 모두 볼 수 있다.
화면은 React(`frontend/`, [react.md](react.md)) — 서버가 빌드 결과 `frontend/dist` 를 내려주고, `/api` 밖의 모르는 주소(`/run` · `/admin/order` …)는 `index.html` 이 받는다.

| 메뉴 | API | 하는 일 |
|---|---|---|
| 시나리오 등록 | `POST /api/register/analyze` | ①②③ + 게이트. `Accept: application/x-ndjson` 이면 단계 시작마다 진행 줄 |
| | `POST /api/register/ir` | 검토 초안(`review-*.json`)을 만들고 바로 IR 생성 (스트림 첫 줄이 검토 초안) |
| | `GET · POST /api/register/scenarios` · `GET · DELETE /api/register/scenarios/{id}` | 등록 시나리오 목록 / 승인 · 등록 / 조회 / 삭제 |
| 확인용 | `POST /api/inspect/approve` | 승인 — 승인 기록(`data/approved/`) + IR 생성 입력(`tdg-*.json`) |
| | `POST /api/inspect/ir` · `GET /api/inspect/ir/approved` · `GET /api/inspect/ir/budget` | 승인본으로 IR 생성 · 승인본 목록 · STEP 수 기반 예산 |
| | `GET /api/inspect/ir/logs` · `GET /api/inspect/ir/logs/{파일}` | IR 생성 기록 표 · JSONL 로그 받기 |
| | `GET · POST /api/inspect/ir/reviews/…` | IR 입력 검토 (API 전용, [scenario-ir-input-review.md](scenario-ir-input-review.md)) |
| 시나리오 실행 | `POST /api/run/dry-run` | 실행 확인 → 드라이런 → 실행 이력 |
| 실행 이력 | `GET /api/history/runs` | 실행 이력 |
| 관리자 | `GET /api/admin/{조각}` (catalog · metadata · operations · graphs · codes · rules · baselines · review · environment · preprocessing) · `GET /api/admin/graph-review` · `POST /api/admin/graphs/match` | 화면 데이터를 조각으로 · 검수 목록의 그래프 부분 · 그래프 화살표의 API 후보 |
| | `PUT /api/admin/graphs/{id}` · `POST /api/admin/rules` · `DELETE /api/admin/rules/{id}` · `PUT /api/admin/baselines` · `POST /api/admin/build` | 그래프 · 보정 규칙 · Baseline · 다시 빌드 (응답은 결과만 — 화면은 바뀐 조각을 다시 읽는다) |
| | `POST /api/admin/preprocessing/refresh` · `PUT /api/admin/preprocessing/baselines` · `GET /api/admin/preprocessing/status` | 전처리 산출물 다시 읽기 · 전처리 Baseline 등록 · 머리 상태 줄(개수 · 경고) |
| 공통 | `GET /api/common/health` | 서버 확인 (`fake_llm` — 가짜 LLM 으로 띄운 서버인지) |

## 저장 파일

| 위치 | 내용 | 저장소 |
|---|---|---|
| `data/registered/` | 등록 시나리오 | 넣지 않음 |
| `data/runs/` | 실행 이력 | 넣지 않음 |
| `data/approved/` | 확인용 화면 승인 기록 | 넣지 않음 |
| `data/ir_inputs/` | IR 생성 입력 — 승인본 `tdg-*.json` · 검토 초안 `review-*.json` | 넣지 않음 |
| `frontend/dist/` | 화면 빌드 결과 (`npm run build`) | 넣지 않음 |
| `data/out/traces/` · `scenario_ir_drafts/` · `scenario_ir_logs/` | 트레이스 · IR · 생성 로그 | 넣지 않음 |
| `data/config/rules.ui.yaml` | 화면에서 넣은 보정 규칙 | 환경마다 다름 |
