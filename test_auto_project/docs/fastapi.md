# FastAPI 전환 계획

예전 서버(`src/tap/ui/serve.py` — 표준 라이브러리 `http.server`)를 FastAPI 로 옮겼다 (2026-11-12, 0~4단계 완료 — 8절). 화면을 React 로 옮기기 전 단계다.
화면은 그 뒤 React 로 옮겼다 ([react.md](react.md), 2026-11-13) — 지금 서버는 `web/` 대신 `frontend/dist` 를 내려준다 (3.6). 아래 '지금 경로' · `web/` 은 전환 당시 기준이다.
작성: 2026-11-12. 이 문서가 전환 작업의 기준이다 — 작업하면서 바뀐 결정은 이 문서를 먼저 고친다.

## 1. 목적과 범위

| 한다 | 하지 않는다 |
|---|---|
| HTTP 층을 FastAPI 로 바꾼다 (라우터 · 오류 처리 · 스트리밍 · 정적 파일) | ①②③ · IR 생성 · 등록 · 실행의 **로직**을 바꾸지 않는다 |
| API 경로를 **메뉴 이름 기준**으로 바꾸고, HTTP 동사를 정리한다 (조회 GET · 덮어쓰기 PUT · 삭제 DELETE) | 예전 경로를 별칭으로 남기지 않는다 — 화면 JS · 테스트를 같이 고친다 |
| 등록 메뉴의 '검토 초안 만들기'와 'IR 생성'을 API 하나로 합친다 | 화면(React) 작업 — 다음 단계 |
| 지금 화면(`web/`)이 전환 뒤에도 그대로 동작하게 한다 | 요청 · 응답 형식 변경 — 칸 이름 · 값은 그대로 (경로만 바뀜) |

## 2. 전체 구조

```
지금                                              바꾼 뒤
브라우저 (web/ 순수 JS)                             브라우저 (web/ 순수 JS — 다음 단계에 React)
   │ fetch('/api/…')                                 │ fetch('/api/<메뉴>/…')
   ▼                                                 ▼
src/tap/ui/serve.py  (http.server, if 분기 라우팅)    src/tap/api/  (FastAPI + uvicorn)
   ├─ 정적 파일 web/                                  ├─ app.py        create_app(root, llm=None)
   ├─ /tap-data.js                                    ├─ routers/      메뉴별 라우터
   └─ 로직이 처리기 안에 섞여 있음                      ├─ services.py   HTTP 와 무관한 처리 함수
                                                     ├─ streaming.py  진행 이벤트 → NDJSON 스트림
                                                     └─ 정적 파일 web/ · /tap-data.js
            ▼                                                 ▼
        같은 로직 — tap.cli.analyze_select · tap.apis.gate · tap.ir.handoff · tap.ir.draft_build · tap.ir.input_review · tap.ui.export …
```

### 폴더

```
src/tap/api/
├── __init__.py
├── app.py              앱 만들기 — 라우터 등록 · 오류 처리기 · 캐시 헤더 · 정적 파일 · 앱 상태(root · llm · pending · 잠금)
├── services.py         serve.py 의 처리 로직을 옮긴 함수 (root · 상태 · 요청 dict 를 받아 dict 를 돌려준다)
├── streaming.py        작업을 스레드에서 돌리고, 진행 이벤트를 큐로 받아 NDJSON 으로 내보내는 도우미
└── routers/
    ├── register.py     시나리오 등록        /api/register/…
    ├── inspect.py      시나리오 등록(확인용) /api/inspect/…     (IR 화면 부분은 혜정 코드에서 옮김)
    ├── run.py          시나리오 실행        /api/run/…
    ├── history.py      실행 이력            /api/history/…
    ├── admin.py        관리자 메뉴          /api/admin/…      (전처리 부분은 혜정 코드에서 옮김)
    └── common.py       공통                 /api/common/…
```

- `src/tap/ui/serve.py` 는 전환이 끝나면 지운다. `src/tap/ui/export.py`(화면 데이터) · `src/tap/ui/preprocessing.py`(전처리 조회)는 그대로 쓴다.
- `tap.cli serve` 는 uvicorn 으로 앱을 띄운다. 포트 8765 · `--host` 옵션은 그대로.

### 서버 상태

| 상태 | 위치 | 설명 |
|---|---|---|
| `root` | `app.state.root` | 저장소 루트 — 데이터 · 설정 · 화면 파일 위치 |
| `llm` | `app.state.llm` | 테스트에서 가짜 LLM 을 끼울 때. 없으면 `.env` 의 OpenAI |
| `pending` | `app.state.pending` + `threading.Lock` | 분석 결과 (선택 해시 → 업무 · 경로 · API 선택 · 게이트 · 승인). **승인 · 등록 판단은 이것으로만 한다** (화면이 보낸 값은 믿지 않는다). 서버를 다시 띄우면 사라진다 — 지금과 같다 |

## 3. API 목록

모든 요청 · 응답 본문은 JSON(UTF-8). 아래 '요청 · 응답'의 칸 이름 · 값은 지금 서버와 같다.

### 3.1 시나리오 등록 — `/api/register`

| 동사 · 경로 | 지금 경로 | 하는 일 | 요청 → 응답 |
|---|---|---|---|
| `POST /api/register/analyze` | `POST /api/select` | ① 요청 이해 → ② 경로 → ③ API 선택 → 권한 등급 · 승인 게이트. 결과를 `pending` 에 둔다 | `{utterance, stop_retry?}` → `{request, tasks, paths, apis, gate, trace, notes, trace_file}`. 실패 400 `{error, trace}` |
| | | `Accept: application/x-ndjson` 이면 진행 스트림 | `{"event":"stage","stage":"intent"\|"paths"\|"apis"}` … 마지막 `{"event":"done"\|"error","result":…}` |
| `POST /api/register/ir` | `POST /api/review-draft` + `POST /api/scenario-ir-drafts` | **합침.** 분석 결과로 검토 초안(`data/ir_inputs/review-*.json`)을 만들고 바로 IR 을 생성한다. 게이트가 차단 · 실행할 것 없음이면 400. IR 자료가 모자라면 400 `{error, missing}` | `{selection_hash, generation_options?}` → `{review: {filename, file, steps:[{step_id, source_step}]}, ir, file, usage, step_previews, log_file, log_url}` |
| | | `Accept: application/x-ndjson` 이면 진행 스트림 | 첫 줄 `{"event":"review_draft","filename","file","steps"}` → IR 이벤트(`generation_start` · `scenario_steps` · `step_preview` …) → 마지막 `{"event":"generation_complete","result"}` 또는 `{"event":"generation_error","error","log_file","log_url"}` |
| `GET /api/register/scenarios` | (화면 데이터 `registered` 에 섞여 있음) | 등록 시나리오 목록 (요약) | → `{scenarios: [{id, name, utterance, domains, registered_at, catalog_version, approver, steps, irreversible, confirm_steps}]}` |
| `POST /api/register/scenarios` | `POST /api/register` | 승인하고 등록 — 서버가 계산한 게이트로 승인, 검토 초안 · IR 이 이 분석 결과로 만든 것인지 확인, `data/registered/rs-*.json` 에 고정 | `{selection_hash, name, approver, steps, review_file, ir_file}` → `{scenario, id}`. 승인이 모자라면 400 `{error, refused:true}` |
| `GET /api/register/scenarios/{id}` | `GET /api/registered/{id}` | 등록 시나리오 전체 | → 등록 기록. 없으면 404 |
| `DELETE /api/register/scenarios/{id}` | `POST /api/registered/delete` | 등록 시나리오 삭제 | → `{ok:true}` |

### 3.2 시나리오 등록(확인용) — `/api/inspect`

분석은 등록 메뉴의 `POST /api/register/analyze` 를 같이 쓴다 (JSON 응답).

| 동사 · 경로 | 지금 경로 | 하는 일 | 요청 → 응답 |
|---|---|---|---|
| `POST /api/inspect/approve` | `POST /api/approve` | 확인용 화면의 승인 — 승인 기록(`data/approved/`) + IR 생성 입력(`data/ir_inputs/tdg-*.json`) | `{selection_hash, approver, scenario, steps}` → `{approval, file, confirm_steps, ir_handoff:{filename, file, steps}\|{filename:null, error, missing?}}`. 모자라면 400 `{error, refused:true}` |
| `POST /api/inspect/ir` | `POST /api/scenario-ir-drafts` | 저장된 승인본(파일 이름)으로 IR 생성 | `{approved_filename, generation_options?, generation_mode?, generation_config?}` → `{ir, file, usage, step_previews, log_file, log_url}`. ndjson 스트림 지원. `budget` · `budget_policy` 를 보내면 400 |
| `GET /api/inspect/ir/approved` | `GET /api/approved-selections` | 승인본 목록 (검토 초안 제외) · 생성 기본값 | → `{files:[{filename, original_question, approval_status}], defaults, default_generation_options, default_generation_mode, generation_modes}` |
| `GET /api/inspect/ir/budget?filename=` | `GET /api/scenario-ir-budget` | 승인본의 STEP 수 기반 예산 | → `{budget}`. 오류 400 |
| `GET /api/inspect/ir/logs` | `GET /api/scenario-ir-log-summaries` | IR 생성 기록 요약 | → `{runs:[…]}` |
| `GET /api/inspect/ir/logs/{file}` | `GET /api/scenario-ir-logs/{file}` | 생성 로그 JSONL 내려받기 — 이름은 `IRRUN-…\.jsonl` 만, 폴더 밖 경로 거부 | → 파일 (`application/x-ndjson`, `Content-Disposition: attachment`). 없으면 404 |
| `GET /api/inspect/ir/reviews` | `GET /api/scenario-ir-reviews` | IR 입력 검토 목록 (API 전용 기능) | → `{reviews}` |
| `GET /api/inspect/ir/reviews/{scenario_id}` | `GET /api/scenario-ir-reviews/{id}` | 검토 상태 · 결정 · 미리보기 | → 검토 상태. 오류 400 |
| `POST /api/inspect/ir/reviews/{scenario_id}/decisions` | 같은 경로 (`/api/scenario-ir-reviews/…`) | 입력 결정 저장 — **값에서 지시문 검사** | `{expected_revision, decisions:[…]}` → 검토 상태. 충돌 409 |
| `POST /api/inspect/ir/reviews/{scenario_id}/confirm` | 같은 경로 | 결정본 확정 | `{expected_revision}` → 검토 상태. 충돌 409 |

### 3.3 시나리오 실행 — `/api/run`

| 동사 · 경로 | 지금 경로 | 하는 일 | 요청 → 응답 |
|---|---|---|---|
| `POST /api/run/dry-run` | `POST /api/registered/run` | 시나리오마다 실행 확인(승인 · 선택 해시 · 이번 실행 R2 확인 · 재승인 필요) → IR 로 요청을 만들어 `data/runs/` 에 남김. 하나라도 안 되면 아무것도 남기지 않음 | `{items:[{id, n, confirm}]}` → `{run}`. 거부 400 |

등록 시나리오 목록은 `GET /api/register/scenarios` 를 같이 쓴다.

### 3.4 실행 이력 — `/api/history`

| 동사 · 경로 | 지금 경로 | 하는 일 | 요청 → 응답 |
|---|---|---|---|
| `GET /api/history/runs` | (화면 데이터 `runs` 에 섞여 있음) | 실행 이력 (최신순) | → `{runs:[…]}` |

### 3.5 관리자 메뉴 — `/api/admin`

| 동사 · 경로 | 지금 경로 | 하는 일 | 요청 → 응답 |
|---|---|---|---|
| `PUT /api/admin/graphs/{graph_id}` | `POST /api/graph/save` | 상태 그래프 저장 — 노드 흐름만, 기존 파일 위에 합침, 이전 파일은 `data/out/graph_history/` | `{yaml}` → `{file, kept, backup}` |
| `POST /api/admin/rules` | `POST /api/rules` | 화면 보정 규칙 추가 → `rules.ui.yaml` + 다시 빌드 | `{place, doc, item, dom, target, body}` → `{build}` |
| `DELETE /api/admin/rules/{id}` | `POST /api/rules/delete` | 화면 규칙 삭제 + 다시 빌드 | → `{build}` |
| `PUT /api/admin/baselines` | `POST /api/baseline` | Baseline Request 저장 (`data/baselines/`) | `{api_id, body}` → `{file}` |
| `POST /api/admin/build` | `POST /api/build` | 명세 · 설정 다시 읽어 빌드 | → `{build, changed}` |
| `POST /api/admin/preprocessing/refresh` | `POST /api/preprocessing/refresh` | 전처리 JSON 다시 읽기 (노트북은 실행하지 않음) | → `{counts, warnings, loaded_at}` |
| `GET /api/admin/preprocessing/status` | (React R4 에서 추가) | 머리의 전처리 상태 줄 — 개수 · 경고만 (산출물 본문은 `GET /api/admin/preprocessing`, 약 3MB) | → `{counts, warnings, loaded_at}` |
| `PUT /api/admin/preprocessing/baselines` | `POST /api/preprocessing/baseline` | 전처리 Baseline 등록 — **값에서 지시문 검사** | `{selected_api_id, values}` → `{file}` |

### 3.6 공통 — `/api/common` · 정적 파일

관리자 쓰기 응답(3.5)에 붙던 화면 데이터 전체(`data`)는 React R6 에서 뺐다 — 화면은 바뀐 조각을 `GET /api/admin/{조각}` 으로 다시 읽는다.

| 동사 · 경로 | 지금 경로 | 하는 일 |
|---|---|---|
| `GET /api/common/health` | `GET /api/health` | 서버 모드 확인 → `{ok:true, fake_llm}` |
| `GET /<주소>` (`/api` 밖) | (React R6) | 화면 — `frontend/dist` 에 있는 파일은 그대로, 나머지(`/run` · `/admin/order` …)는 `index.html`. 빌드가 없으면 503 + 빌드 명령 안내 |
| ~~`GET /api/common/data`~~ · ~~`GET /tap-data.js`~~ | | 예전 화면용 화면 데이터 — React R6 에서 지웠다 (조각 API 로 대체) |

## 4. 공통 규칙

- **오류 형식은 `{"error": "…"}` 그대로.** FastAPI 기본(`{"detail"}`)을 쓰지 않는다 — 오류 처리기로 맞춘다.
  - 입력 · 검사 오류(`ValueError`) 400, 검토 충돌(`ReviewConflict`) 409, 없는 자원 404, 그 밖 500 (`"<예외 이름>: <내용>"`).
  - IR 생성 오류는 `log_file` · `log_url` 을 같이 돌려준다. 승인 거부는 `refused: true` 를 붙인다.
- **진행 스트림(NDJSON)**: `Accept: application/x-ndjson` 일 때만. 한 줄에 JSON 하나, 이벤트가 생길 때마다 바로 보낸다 (모아서 보내지 않는다).
  헤더 `Content-Type: application/x-ndjson; charset=utf-8` · `Cache-Control: no-store` · `X-Accel-Buffering: no`. 화면이 연결을 끊어도 서버 작업은 조용히 끝낸다.
- **화면 파일 캐시**: `index.html` 등은 `Cache-Control: no-cache` (새로 빌드한 화면이 새로고침으로 바로 보이게), 이름에 내용 해시가 붙은 `assets/` 는 `public, max-age=31536000, immutable`.
- **인증 없음 · 로컬 전용**: 기본 `127.0.0.1`. CORS 는 열지 않는다 — React 개발 서버는 다음 단계에서 프록시로 붙인다.
- **경로 이름**: 메뉴 영문 이름(`register` · `inspect` · `run` · `history` · `admin` · `common`) 아래, 자원은 복수형 명사(`scenarios` · `rules` · `graphs` …), 동작은 동사(`analyze` · `approve` · `dry-run` · `build` · `refresh`). 단어 구분은 하이픈.
- **여러 메뉴가 같이 쓰는 API 는 주로 쓰는 메뉴 아래 하나만** 둔다 (분석 · 등록 시나리오 목록 → `register`).

## 5. 전환 순서

| 단계 | 할 일 | 끝났다는 기준 |
|---|---|---|
| **0. 준비** | `pyproject.toml` 에 `fastapi` · `uvicorn` 추가, dev 에 `httpx` (모두 버전 고정). 테스트가 없는 API(`/api/build`)는 지금 서버 기준으로 테스트를 먼저 추가 | 지금 서버로 pytest · node 통과 |
| **1. 앱 · 서비스 · 라우터** | `services.py` 로 처리 로직을 옮기고(`serve.py` 의 모듈 함수 + 처리기 안의 로직), 메뉴별 라우터를 3절 경로로 작성. 오류 처리기 · 스트리밍 도우미 · 정적 파일 · `/tap-data.js` · 캐시 헤더. `tap.cli serve` 를 uvicorn 으로 | 앱이 뜨고 3절의 모든 경로가 응답 |
| **2. 화면 경로 수정** | `web/` 의 호출 경로를 새 경로 · 동사로 (아래 6.4 목록). 등록 화면은 review-draft + IR 두 번 호출 → `/api/register/ir` 한 번 | 화면 점검(6.3) 통과 |
| **3. 테스트 전환** | 테스트의 서버 띄우는 부분(fixture)을 FastAPI 앱으로. 호출 경로 · 동사를 새 것으로. **검사 내용(assert)은 바꾸지 않는다** | pytest · node 통과 |
| **4. 정리** | `serve.py` 삭제, 남은 참조 검사(예전 경로 문자열이 코드 · 테스트 · 문서에 없을 것), 문서 수정(6.6) | 예전 경로 0건 |
| **5. React 준비 (다음 작업 시작 때)** | API 마다 pydantic 요청 · 응답 모델 → OpenAPI 명세 → React(TypeScript) 타입 생성, `GET /api/common/data` 를 화면 데이터 대신 쓰는 구조로 | React 작업 시작 |

## 6. 작업 기준

### 6.1 코드

- **로직은 옮기기만 한다.** 처리 순서 · 검사 · 저장 위치 · 응답 칸을 바꾸지 않는다. 바꿔야 할 것이 보이면 이 문서에 적고 전환 뒤 따로 한다.
- **라우터는 일반 함수(`def`)로 쓴다** — LLM 호출 · 파일 쓰기가 동기 코드라 `async def` 로 쓰면 그동안 다른 요청이 멈춘다. FastAPI 가 스레드풀에서 돌린다.
- **진행 스트림**: 작업(분석 · IR 생성)을 별도 스레드에서 돌리고, 진행 콜백(`on_stage` · `on_event`)이 이벤트를 `queue.Queue` 에 넣고, `StreamingResponse` 가 큐에서 꺼내 한 줄씩 보낸다. 작업 예외는 마지막 `error` 이벤트로.
- **`pending` 은 잠금 안에서 읽고 쓴다.**
- **테스트가 바꿔 끼우는 함수는 호출할 때 가져온다** — 테스트가 `tap.ir.draft_build.generate` 를 가짜로 바꾸므로, 서비스 함수 안에서 `from tap.ir.draft_build import generate` 를 함수 실행 때 한다 (모듈 맨 위에서 가져오면 가짜가 안 먹힌다).
- **사람이 넣는 값의 지시문 검사**(`detect_in_values`)는 IR 입력 검토 결정 · 전처리 Baseline 두 API 에서 그대로 한다.
- 요청 본문은 1단계에서는 지금처럼 dict 로 받는다 (형식 검사 · 오류 문구가 지금과 같게). pydantic 모델은 5단계.
- 파일 경로를 받는 API(로그 · 승인본 · 등록 id)는 지금의 이름 검사 · 폴더 밖 거부를 그대로 둔다.

### 6.2 테스트

- `.venv/bin/python -m pytest -q` · `node --test tests/*.cjs`(당시 — node 테스트는 React R6 에서 Vitest 로) 가 단계마다 모두 통과해야 다음 단계로 간다.
- 테스트 서버는 `create_app(root, llm=fake_llm)` 으로 만든다. 실행 결과물 폴더는 복사하지 않는다 (`tests/test_ui.py` 의 `COPY_DATA`).
- 진행 스트림 테스트: 이벤트가 **끝까지 모였다가 한꺼번에** 오지 않는지 — 첫 `stage` 이벤트가 마지막 결과보다 먼저 도착하는지 확인한다.
- `/api/register/ir` 합친 API: 검토 초안 이벤트 → IR 이벤트 → 완료 순서, 차단 게이트 400, 자료 부족 400 을 테스트한다.

### 6.3 화면 점검 (실제 서버 · 실제 LLM)

단계 1 · 2 · 4 끝에 한 번씩:

1. 시나리오 등록: 이름 · 요청 입력 → 분석(진행 표시가 단계마다 바뀜) → IR(단계별 입력값 표) → 승인 · 등록 → 목록에 보임 → 열기 · 삭제
2. 시나리오 실행: 등록 시나리오 담기 → R2 확인 → 드라이런(입력값 표 · 요청 XML) → 실행 이력
3. 확인용: 분석 → 승인 → 혜정 IR 영역 자동 생성(로그 · STEP 상세) → 승인본 골라 다시 생성 · 로그 내려받기
4. 관리자: 그래프 열기 · 저장, 규칙 추가 · 삭제, Baseline 저장, 다시 빌드, 전처리 갱신
5. 브라우저 콘솔 오류 0

### 6.4 화면 호출 경로 수정 대상

| 파일 | 바꿀 호출 |
|---|---|
| `web/scenario-register.js` | select → `register/analyze`, review-draft + scenario-ir-drafts → `register/ir` (검토 초안 파일 이름은 `review_draft` 이벤트에서), register → `register/scenarios`, registered/{id} · delete → `register/scenarios/{id}` (GET · DELETE) |
| `web/scenario-run.js` | registered/run → `run/dry-run` |
| `web/offline-ui.html` | select → `register/analyze`, approve → `inspect/approve`, rules · rules/delete · baseline · build → `admin/…`, health → `common/health` |
| `web/scenario-ir-draft.js` (혜정) | approved-selections · scenario-ir-budget · scenario-ir-log-summaries · scenario-ir-logs · scenario-ir-reviews · scenario-ir-drafts → `inspect/…` |
| `web/graph-editor.js` | graph/save → `PUT admin/graphs/{graph_id}`, health → `common/health` |
| `web/preprocessing-ui.js` (혜정) | preprocessing/refresh · baseline → `admin/preprocessing/…` |

### 6.5 커밋

- 단계마다 커밋한다 (0 · 1+2 · 3 · 4). 메시지 `test_auto_project: …`, 끝에 공동 작성자 줄.
- 커밋 전: pytest · node 통과, `data/config/rules.ui.yaml` 은 커밋하지 않는다.
- 혜정 코드(`scenario-ir-draft.js` · `preprocessing-ui.js` · IR · 전처리 API 처리)를 옮기거나 고친 내용은 커밋 메시지와 혜정에게 따로 알린다.

### 6.6 같이 고칠 문서

`README.md`(명령 · 구조) · `AGENTS.md`(실행) · `docs/architecture.md`(서버 API 표 · 저장 파일) · `docs/scenario-ir.md`(IR · 검토 API 경로) · 이 문서(진행 상태).

## 7. 정해 둔 것 · 열린 것

| 항목 | 상태 |
|---|---|
| 메뉴 이름으로 경로 구분, 예전 경로 별칭 없음 | 결정 (2026-11-12) |
| 등록 메뉴의 검토 초안 + IR 생성을 `POST /api/register/ir` 하나로 | 결정 (2026-11-12) |
| 조회 GET · 덮어쓰기 PUT · 삭제 DELETE | 제안대로 진행 |
| 확인용 메뉴 경로 이름 `inspect` | 결정 (2026-11-12) |
| 작업 브랜치 | `feature/fastapi` (`cleanup/final-repo` 에서 분기) |
| pydantic 요청 · 응답 모델 | 5단계 (React 시작 때) |

## 8. 진행 상태

| 단계 | 상태 |
|---|---|
| 0. 준비 | 완료 — fastapi 0.162.5 · uvicorn 0.54.0 · httpx 0.28.1 고정, `/api/build` 테스트 추가 |
| 1. 앱 · 서비스 · 라우터 | 완료 — `src/tap/api/` (API 25개), `tap.cli serve` 는 uvicorn |
| 2. 화면 경로 수정 | 완료 — 화면 점검 통과 (스트림: 요청 이해 0.5초 · 경로 4.2초 · API 7.0초에 각각 도착) |
| 3. 테스트 전환 | 완료 — `tests/app_server.py` (FastAPI 앱을 실제 포트로), pytest 331 · node 통과 |
| 4. 정리 | 완료 — `ui/serve.py` 삭제, 예전 경로 문자열 0건 (코드 · 테스트 · 문서), README · AGENTS · architecture · scenario-ir 문서 수정 |
| 5. React 준비 | 완료 — React 전환 R0 에서 ([react.md](react.md) 10절). R6 에서 화면 데이터 API 정리 (3.6) |
