# React 전환 계획

지금 화면(`web/` — HTML · CSS · 순수 JavaScript 7,100줄)을 React 로 **전부** 옮긴다. 서버는 FastAPI 로 이미 옮겼다 ([fastapi.md](fastapi.md)).
작성: 2026-11-12. 이 문서가 전환 작업의 기준이다 — 작업하면서 바뀐 결정은 이 문서를 먼저 고친다.

## 1. 목적과 범위

| 한다 | 하지 않는다 |
|---|---|
| 5개 메뉴의 실제 데이터 화면을 모두 React 로 옮긴다 (등록 · 확인용 · 실행 · 이력 · 관리자, 상태 그래프 편집기 · 혜정 IR · 전처리 화면 포함) | 서버 로직 변경 — 화면이 필요로 하는 API 만 더한다 (6절) |
| 화면 동작 · 문구 · 흐름은 지금과 같게 (이번에 정리한 최종 화면 기준) | 새 기능 — 옮긴 뒤 따로 |
| 다 옮기면 FastAPI 가 React 빌드 결과를 내려주고 `web/` · `/tap-data.js` 를 지운다 | **시연 데이터 모드는 옮기지 않는다** (서버 없이 보는 가짜 데이터 — 약 3,000줄) |

옮기지 않고 버리는 것: 시연 데이터 모드 전체, 실행 메뉴의 '실행 세트'(서버 모드에서 이미 숨김), 관리자의 숨김 카드(추출 결과 · 도메인 명세 소스 · 간선 레지스트리 · 거절 로그 · 정적 그래프 그림), 일괄 실행 · 롤백 시연.

## 2. 기술 선택

| 영역 | 선택 | 이유 |
|---|---|---|
| 빌드 · 개발 서버 | **Vite** | 설정이 적고 빠르다. 개발 때 `/api` 를 FastAPI 로 넘기는 프록시 |
| 언어 | **TypeScript** | API 응답(업무 · 경로 · 단계 · 게이트 · IR)이 깊고 복잡하다. FastAPI 의 OpenAPI 로 타입을 자동으로 만든다 |
| 화면 이동 | **React Router** | 메뉴마다 주소 (`/register` · `/inspect` · `/run` · `/history` · `/admin/:scope`) — 새로고침 · 링크 공유 |
| 서버 데이터 | **TanStack Query** | 조회 · 캐시 · 다시 불러오기 · 저장 뒤 갱신. 전역 상태 라이브러리는 두지 않는다 |
| 진행 스트림 | 직접 만든 훅 `useNdjson` | `fetch` + `ReadableStream` 으로 한 줄씩 (지금 `readLines` 와 같은 방식) |
| 상태 그래프 편집기 | **React Flow (`@xyflow/react`)** | 노드 끌기 · 화살표 잇기 · 확대 · 미니맵을 직접 만들지 않는다 |
| 스타일 | **CSS Modules + 지금 디자인 토큰(CSS 변수)** | 지금 화면의 색 · 간격 · 다크 모드 변수를 그대로 가져온다. 컴포넌트 라이브러리는 쓰지 않는다 (7절 결정 1) |
| 테스트 | **Vitest + React Testing Library + MSW**, 화면 끝까지는 **Playwright** | 단위 · 컴포넌트는 가짜 API(MSW)로, 실제 서버 흐름은 Playwright 로 |
| 린트 · 포맷 | ESLint · Prettier | |
| Node | 20 이상 (지금 개발 환경 24) | `package.json` 의 `engines` 로 고정 |
| 버전 | `package.json` 에 정확한 버전으로 고정 (`^` 없음), `package-lock.json` 커밋 | `pyproject.toml` 과 같은 원칙. TypeScript 는 5.9 — 7(새 컴파일러)은 typescript-eslint · openapi-typescript 가 아직 받지 않는다 |

## 3. 전체 구조

```
지금                                         바꾼 뒤
web/  ── FastAPI 가 그대로 내려줌             frontend/  ── 개발: Vite(5173) → /api 는 FastAPI(8765) 로 프록시
  offline-ui.html (5,120줄 한 파일)                         빌드: frontend/dist → FastAPI 가 내려줌 (모르는 주소는 index.html)
  window.TAP_DATA (/tap-data.js 한 덩어리)      API 마다 필요한 것만 (TanStack Query)
```

### 폴더

```
frontend/
├── package.json · vite.config.ts(Vitest 설정 포함) · tsconfig.json · eslint.config.js · .prettierrc.json · playwright.config.ts
├── e2e/                              Playwright — 실제 서버(가짜 LLM)로 화면 끝까지
├── index.html
└── src/
    ├── main.tsx · App.tsx            라우터 · 쿼리 클라이언트 · 공통 레이아웃(사이드 메뉴 · 머리)
    ├── api/
    │   ├── schema.d.ts               FastAPI OpenAPI 로 자동 생성 (손으로 고치지 않는다)
    │   ├── client.ts                 fetch 감싸기 — {"error"} 를 오류로, 동사 · JSON
    │   ├── stream.ts                 useNdjson — NDJSON 한 줄씩
    │   └── queries.ts                메뉴별 조회 · 저장 훅 (useRegisteredScenarios · useAnalyze …)
    ├── styles/                       tokens.css (지금 :root 변수 · 다크 모드) · base.css (글꼴 · 입력 · 버튼 공통 클래스)
    ├── components/                   공통 — Layout · Card · Pill · Stepper · Spinner (R0) · ParamTable · scenario.module.css (등록 · 실행 공용 모양). Modal · Toast 는 처음 쓰는 단계에서
    ├── lib/                          menus(사이드 메뉴) · storage(localStorage 감싸기) · store(화면 밖 진행 상태) · format(도메인 이름 · API 짧은 이름)
    ├── test/                         Vitest 준비 — MSW 가짜 API(server.ts) · 그리기 도우미(render.tsx)
    └── pages/
        ├── register/                 시나리오 등록 (최종)
        ├── inspect/                  시나리오 등록(확인용) — 분석 카드 · 승인 게이트 · ir/(혜정 IR 영역)
        ├── run/                      시나리오 실행
        ├── history/                  실행 이력
        └── admin/                    관리자 — overview(전사) · domain(도메인) · graph-editor/ · data-docs/ · rules/ · baselines/ · preprocessing/
```

- FastAPI 쪽: `app.mount("/", StaticFiles(web))` 를 `frontend/dist` 로 바꾸고, `/api` 가 아닌 모르는 주소는 `index.html` (React Router 가 처리).
- `npm run build` 결과(`frontend/dist`)와 `node_modules` 는 저장소에 넣지 않는다.

## 4. 화면 목록 — 옮길 기능

### 4.1 시나리오 등록 (지금 `scenario-register.js` 396줄)

| 기능 | API |
|---|---|
| 등록 시나리오 목록 (상태 · 재승인 필요 · 삭제 두 번 확인) · 열기(읽기 전용 보기 · 닫기) | `GET /api/register/scenarios` · `GET · DELETE /api/register/scenarios/{id}` |
| 입력: 시나리오 이름 · 자연어 요청 · 생성 옵션(압축 1 · 2, 브라우저에 기억) · Ctrl+Enter | — |
| 진행 표시 4단계 (요청 이해 → 경로 → API → 시나리오 생성, 생성은 n/N) · 새로고침 경고 · 메뉴 이동해도 계속 | `POST /api/register/analyze` (스트림) · `POST /api/register/ir` (스트림) |
| 미리보기: 업무 설명 · 태그 · 단계 카드 · 입력값 표(필드명 · 필드설명 · 입력값) · 되돌릴 수 없음 / 확인 필요 표시 | 위 결과 + 화면 데이터(필드 한글명) |
| 확인할 것 체크 · 메모(접기) · 승인자(기억) · 승인하고 등록 · 실패 · 다시 만들기 | `POST /api/register/scenarios` |
| 멈춤 카드 (분석 실패 · 차단 · 실행할 것 없음) | |

### 4.2 시나리오 등록(확인용) (지금 `offline-ui.html` 의 3단계 블록 + `scenario-ir-draft.js` 610줄)

| 기능 | API |
|---|---|
| 입력 · 분석 버튼 · 스피너 · 도메인 태그 · 중지조건 · 재시도 토글 | `POST /api/register/analyze` |
| 결과 카드: 요약 · ① 업무 · ② 경로 · ③ API 선택(후보 · 점수 · 확정 검사 펼치기) · 트레이스(단계별 시간 · 토큰) · 확인할 것 · JSON 보기 | |
| 승인 게이트: 단계 표(등급 · 등록 때 · 실행 때) · 차단 목록 · 단계 확인 체크 → 승인 버튼 켜기 · 승인자 | `POST /api/inspect/approve` |
| **혜정 IR 영역**: 승인본 고르기 · 생성 옵션 3개 · 예산 표시 · IR 다시 생성 · 진행 표(LLM 턴 · 도구 호출 · 백엔드 행, 요청 / 응답 탭 상세) · STEP 목록과 상세(업무 조건 · 입력값 · Baseline XML 바뀐 줄) · 전체 IR JSON · 누적 생성 기록 표(옵션 · 날짜 필터) · JSONL 내려받기 | `GET /api/inspect/ir/approved` · `GET /api/inspect/ir/budget` · `POST /api/inspect/ir` (스트림) · `GET /api/inspect/ir/logs` · `GET /api/inspect/ir/logs/{file}` |

IR 입력 검토(승인게이트) 화면은 지금도 숨김이라 옮기지 않는다 (API 는 남는다).

### 4.3 시나리오 실행 (지금 `scenario-run.js` 97줄)

| 기능 | API |
|---|---|
| 등록 시나리오 목록 · 검색 · 재승인 필요는 담기 막기 | `GET /api/register/scenarios` |
| 선택된 시나리오 표 · 반복 횟수(1~20) · 빼기 · R2 '이번 실행에서 확인' 체크 → 드라이런 버튼 켜기 | |
| 드라이런 결과: 시나리오 #k 묶음 · 단계별 입력값 표 · 보낼 요청 XML 펼치기 · 메모 · 이력으로 이동 | `POST /api/run/dry-run` |

### 4.4 실행 이력

| 기능 | API |
|---|---|
| 이력 표(시각 · 시나리오 · 건수 · 호출 · 미해결 · 종류) · 검색 · 종류 필터 · 행 펼치기(호출 · 되돌리는 순서) | `GET /api/history/runs` |

### 4.5 관리자 메뉴 (지금 `offline-ui.html` 관리자 부분 + `graph-editor.js` 777줄 + `preprocessing-ui.js` 170줄)

| 범위 | 기능 | API |
|---|---|---|
| 위쪽 범위 탭 | 전사 / 도메인 7개 (도메인별 요약 숫자) | 화면 데이터 |
| 전사 | 1단계 산출물 · 검수 목록(규칙으로 확정 못 한 것 · 그래프 검수) | 화면 데이터 |
| | 도메인별 현황 표 · catalog 버전 | 화면 데이터 |
| | 규칙 입력(전사) · 등록된 내역 팝업 · 삭제 | `POST /api/admin/rules` · `DELETE /api/admin/rules/{id}` |
| | Swagger 명세 소스 · 다시 빌드 · 변경 확인 | `POST /api/admin/build` |
| | 데이터 조회 — 문서 8종 팝업 (API Catalog · MetaData · Canonical Schema · Tool Registry · Baseline · Parameter KB · Response Outputs · State Vocabulary, 문서 · API 필터) | 화면 데이터 |
| | 환경과 감사 (허용 환경 · base URL · 승인 · 실행기 상태) | 화면 데이터 |
| 머리 | 전처리 산출물 갱신 | `POST /api/admin/preprocessing/refresh` |
| 도메인 | **상태 그래프 편집기**: 그래프 고르기 · 새 그래프(공통코드 그룹) · 상태 끌어 놓기 · 화살표 잇기 · 업무 이름 · API 후보 미리보기(찾음 / 확인 필요 / 없음) · 확인 후 저장(YAML 보기) | `PUT /api/admin/graphs/{id}` (+ 6절의 매칭 API) |
| | 데이터 조회(그 도메인) · 규칙 입력(도메인) · 등록된 내역 | 위와 같음 |
| | Baseline Request — API 고르기 · 필드 값 입력 · 검사 · 저장 · 등록된 내역 (전처리 Baseline 포함, 혜정) | `PUT /api/admin/baselines` · `PUT /api/admin/preprocessing/baselines` |

## 5. 공통 화면 요소

| 요소 | 지금 | React |
|---|---|---|
| 사이드 메뉴 · 머리(제목 · 데이터 배지 · 전처리 갱신) | `renderNav` · `setView` | `Layout` + React Router |
| 카드 · 표 · 태그 · 상태 알약(st-ok · st-rb …) | 클래스 문자열 | `Card` · `Table` · `Tag` · `Pill` |
| 알림(toast) · 팝업(modal) · 툴팁 | `toast()` · `openModal()` | `Toast` · `Modal` · `Tooltip` |
| 스피너 · 진행 4단계 | `.spinner` · `.fin-steps` | `Spinner` · `Stepper` |
| 입력값 표 | `FinalReg.paramTable` (등록 · 실행 공용) | `ParamTable` |
| 필드 한글명 · 도메인 이름 · API 짧은 이름 | `labelOf` · `RDOM_NAME` · `shortApi` | `lib/format.ts` |
| 다크 모드 · 좁은 화면 | `prefers-color-scheme` · `@media (max-width:900px)` | `tokens.css` 그대로 |

## 6. API 준비 (FastAPI 5단계)

| 할 일 | 내용 |
|---|---|
| 요청 · 응답 모델 | API 마다 pydantic 모델(`tap/api/models.py`) → `/api/openapi.json` 이 칸까지 설명. 칸 이름 · 값은 바꾸지 않는다 (지금 화면 · 테스트가 쓴다). 요청 검사 실패도 400 `{"error"}` (422 를 쓰지 않음), 모델 밖의 칸은 서비스로 넘긴다. 응답 모델은 문서용 — 실행 중 다시 검사하지 않는다(예전 기록에서 서버 오류가 나지 않게). 진행 스트림 줄 모양은 스트림 경로의 `application/x-ndjson` 응답에 `oneOf` 로. 화면 데이터(`/api/admin/{part}` · `/api/common/data`) · 확인용 IR 검토 · 로그는 아직 칸 설명 없음 — 해당 화면을 옮길 때 추가 |
| 타입 자동 생성 | `openapi-typescript` 로 `frontend/src/api/schema.d.ts`. `npm run gen:api` 로 다시 만든다 — 서버 모델을 바꾸면 같이 커밋 |
| 화면 데이터 나누기 | 지금 `/api/common/data` 는 한 덩어리(약 3MB). React 는 필요한 것만: `GET /api/admin/catalog` · `metadata` · `operations`(필드 한글명) · `graphs` · `codes` · `rules` · `review` · `preprocessing` · `environment` — 같은 `ui_data` 를 나눠 돌려준다. 칸마다 필요할 때만 만든다(`tap.ui.export.ui_parts`, R4) — 전처리(약 3MB)가 아닌 칸은 수 ms |
| 그래프 매칭을 서버로 | 그래프 편집기의 API 후보 미리보기는 지금 `graph-editor.js` 가 `graph/match.py` 를 JS 로 **복사**해 계산한다 (두 벌). `POST /api/admin/graphs/match` 로 파이썬 하나만 쓰게 한다 |
| 개발 프록시 | Vite `server.proxy['/api'] = 'http://127.0.0.1:8765'` — CORS 를 열지 않는다. 스트림이 프록시에서 모이지 않는지 확인 |

## 7. 전환 순서

옮기는 동안 `http://127.0.0.1:8765/` 는 지금 화면(`web/`)을 계속 내려주고, React 는 개발 서버(5173)에서 만든다. 마지막 단계에서 한 번에 바꾼다.

| 단계 | 할 일 | 끝났다는 기준 |
|---|---|---|
| **R0. 준비** | FastAPI 5단계(6절) — 모델 · 타입 생성 · 화면 데이터 나누기 · 매칭 API. `frontend/` 만들기(Vite · TS · 린트 · Vitest · Playwright · MSW), 디자인 토큰 옮기기, 레이아웃 · 라우터 · API 클라이언트 · `useNdjson` · 공통 컴포넌트 | 빈 메뉴 5개가 뜨고 `/api/common/health` 를 부름. pytest · node · vitest 통과 |
| **R1. 시나리오 등록** | 4.1 전부 | 6.3 화면 점검 1 (React 화면으로) |
| **R2. 실행 · 이력** | 4.3 · 4.4 | 화면 점검 2 |
| **R3. 확인용** | 4.2 — 분석 카드 · 승인 게이트 · 혜정 IR 영역 | 화면 점검 3 |
| **R4. 관리자** | 4.5 중 그래프 편집기를 뺀 전부 — 범위 탭 · 전사 · 데이터 조회 8종 · 규칙 · 명세 · 환경 · Baseline · 전처리 | 화면 점검 4 (그래프 빼고) |
| **R5. 그래프 편집기** | React Flow 로 — 끌기 · 잇기 · 이름 · 서버 매칭 미리보기 · 새 그래프 · 저장 | 저장한 YAML 이 지금 편집기와 같은 모양 (같은 그래프로 비교) |
| **R6. 바꾸기** | FastAPI 가 `frontend/dist` 를 내려주게, `web/` · `/tap-data.js` · `/api/common/data`(나눈 API 로 대체됐으면) 삭제, node 테스트(`tests/*.cjs`)를 Vitest 로, 문서(README · AGENTS · architecture · fastapi · 이 문서) | 5개 메뉴 화면 점검 통과, 예전 화면 파일 0개 |

## 8. 작업 기준

### 8.1 코드

- **API 는 `src/api/` 를 거쳐서만 부른다.** 컴포넌트에서 `fetch` 를 직접 쓰지 않는다. 타입은 생성된 `schema.d.ts` 에서 가져온다 (손으로 응답 타입을 쓰지 않는다).
- 오류는 서버의 `{"error"}` 문구를 그대로 사용자에게 보여 준다 (지금과 같다). 승인 거부(`refused`)는 따로 표시.
- **진행 스트림**은 `api/stream.ts` 로만 받는다 — 줄마다 상태를 바꾸고, 연결이 끊기면 마지막 상태를 유지, 화면을 떠나도 작업은 끝까지(지금처럼). 새로고침 · 창 닫기는 경고.
  - 스트림 하나면 `useNdjson`.
  - 여러 단계를 잇는 흐름(등록: 분석 → 시나리오 생성 → 등록)은 `postStream` + 화면 밖 저장소(`lib/store.ts`)로 — 예: `pages/register/flow.ts`. 메뉴를 옮겨도 진행 · 입력이 남는다.
- 서버 데이터는 TanStack Query 로만 들고 있는다. 저장(등록 · 삭제 · 규칙 · 빌드) 뒤에는 관련 쿼리를 다시 불러온다 — 지금의 `rerenderAll` 대신.
  - 예외: 혜정 IR 영역의 승인본 목록 · 예산은 'IR 생성을 시작할 때 다시 읽고 → 예산을 산정하고 → 생성'하는 순서에 묶여 있어 생성 진행과 같은 저장소(`pages/inspect/ir/irStore.ts`)에 둔다. 누적 실행 기록은 Query.
- 브라우저에 기억하는 값(승인자 · 생성 옵션 · 고른 탭)은 `localStorage` 를 감싼 훅 하나로, 막혀 있어도 동작하게.
- 컴포넌트는 한 파일 300줄 안쪽으로. 페이지 안에서만 쓰는 것은 그 페이지 폴더에, 두 페이지 이상이 쓰면 `components/` 로.
- 지금 코드에서 옮길 때 **문구 · 흐름을 바꾸지 않는다.** 바꾸고 싶은 것은 이 문서 '나중에' 목록에 적고 전환 뒤에 한다.
- 사용자에게 필요 없는 설명 문구(회색 글씨)를 늘리지 않는다 (11-12 화면 정리 원칙).

### 8.2 접근성 · 화면

- 키보드로 모든 버튼 · 체크 · 표 행을 쓸 수 있게 (지금 화면의 tabindex · Enter/Space 처리 유지), 상태 변화는 `aria-live`, 스피너에는 읽히는 이름.
- 다크 모드 · 좁은 화면(900px 아래 한 열) 유지. 움직임 줄이기 설정 존중.

### 8.3 테스트

| 종류 | 기준 |
|---|---|
| 서버 | `pytest` 통과 (모델 추가 · API 나누기 테스트 포함) |
| 컴포넌트 | Vitest + RTL — 공통 컴포넌트, 각 페이지의 주요 상태(빈 상태 · 진행 · 결과 · 오류 · 차단). API 는 MSW 로 가짜 |
| 스트림 | `useNdjson` — 줄이 나뉘어 와도 · 마지막 줄 줄바꿈 없음 · 진행 줄 없는 JSON 응답 |
| 끝까지 | Playwright — 실제 서버(가짜 LLM 모드)로 등록 → IR → 등록 → 드라이런 → 이력, 확인용 승인 → IR, 관리자 규칙 · 그래프 저장 |
| 실제 LLM 점검 | 단계마다 한 번, [fastapi.md](fastapi.md) 6.3 화면 점검을 React 화면으로 |

Playwright 는 실제 LLM 없이 돈다 — `npm run test:e2e` 가 서버를 `tap.cli serve --fake-llm --temp-data`(8799)로, Vite 를 5199 로 띄운다 (`playwright.config.ts`).

- 가짜 LLM(`src/tap/api/fake.py`): 어떤 요청이든 '배송완료 주문을 배송완료 취소' 업무 하나, IR 은 입력값을 모두 '확인 필요'. 화면 머리에 **가짜 LLM** 배지가 뜬다 (`/api/common/health` 의 `fake_llm`).
- `--temp-data`: `data/` 를 임시 폴더(`/tmp/tap-serve-<포트>`)에 복사해 쓴다 — 테스트 등록 · 실행 기록이 저장소 `data/` 에 남지 않는다. 다음 실행 때 비우고 다시 쓴다.
- 처음 한 번 `npx playwright install chromium`. WSL 에 브라우저 라이브러리(libnss3 · libasound2)가 없으면 `sudo npx playwright install-deps chromium`.
- 가짜 LLM 은 바로 답하므로 스트림이 프록시에서 **조금씩** 오는지는 볼 수 없다 — 실제 LLM 화면 점검(fastapi.md 6.3) 때 확인한다.

### 8.4 커밋 · 협업

- 단계(R0 ~ R6)마다 커밋, 큰 단계는 화면 단위로 나눠도 된다. 커밋 전 pytest · vitest · (있으면) Playwright 통과 — **테스트 결과를 확인한 뒤에 커밋한다.**
- 생성된 타입(`schema.d.ts`)은 서버 모델과 같은 커밋에.
- 혜정 화면(IR 영역 · 전처리 · Baseline 전처리)은 옮기기 전에 혜정과 화면 동작을 확인하고, 옮긴 뒤 알린다. 새 팀원 분담은 7절 단계 단위로 나누기 좋다 (R2 · R4 는 서로 독립).

## 9. 결정 (2026-11-12 — 권장안대로 확정)

| # | 항목 | 결정 |
|---|---|---|
| 1 | 컴포넌트 라이브러리 | 쓰지 않고 지금 디자인 토큰 + CSS Modules (화면 모양 유지 · 의존성 적게). 빨리 만들고 싶으면 shadcn/ui |
| 2 | 화면 데이터 나누기 (6절) | R0 에서 나눈다. 늦추면 R1 은 `/api/common/data` 한 번 받아 캐시로 시작 |
| 3 | 그래프 매칭 서버 API (6절) | R0 에서 추가 — R5 에서 JS 복사본을 없앤다 |
| 4 | Playwright 용 가짜 LLM 서버 옵션 | 테스트 전용 옵션 추가 (운영 실행에는 영향 없음) |
| 5 | 작업 브랜치 | `feature/react` (`feature/fastapi` 에서 분기) |
| 6 | 담당 나누기 | 지은 R0 · R1 · R3, 새 팀원 R2 · R4, 혜정 R3 의 IR 영역 · R4 의 전처리 확인, R5 는 R0 끝나고 정함 |

## 10. 진행 상태

| 단계 | 상태 |
|---|---|
| R0. 준비 (FastAPI 5단계 포함) | 완료 — R0-1 화면 데이터 나누기 · 매칭 API, R0-2 요청 · 응답 모델, R0-3 `frontend/` 뼈대 (메뉴 5개 · 서버 연결 표시 · `useNdjson` · 공통 컴포넌트), R0-4 가짜 LLM 서버 옵션 · Playwright. pytest 335 · node 4 · vitest 16 · Playwright 3 |
| R1. 시나리오 등록 | 완료 — 4.1 전부 (`pages/register/`). 화면 데이터 칸 설명 추가(operations · environment). 화면 점검 1 을 실제 LLM 으로 통과 (진행 표시가 프록시를 거쳐 단계마다 바뀜, 콘솔 오류 0). vitest 32 · Playwright 5 |
| R2. 실행 · 이력 | 완료 — 4.3 · 4.4 전부 (`pages/run/` · `pages/history/`). 등록 · 실행이 같이 쓰는 모양은 `components/scenario.module.css` 로. 등록 목록 · 실행 이력 API 가 화면 데이터 전체를 만들지 않게. 화면 점검 2 를 실제 서버로 통과 (콘솔 오류 0). vitest 41 · Playwright 6 |
| R3. 확인용 | 완료 — 4.2 전부 (`pages/inspect/`, 혜정 IR 영역은 `pages/inspect/ir/`). IR 진행 이벤트 → 로그 행 · STEP 규칙(`irLog.ts`)은 예전 `scenario-ir-draft.js` 에 같은 실제 생성 로그(성공 · 실패)를 흘려 넣어 표 · STEP 이 칸까지 같은지 대조. 트레이스 · 승인본 목록 · 예산 · 실행 기록 응답 모델. vitest 57 · Playwright 7. 화면 점검 3 을 실제 LLM 으로 통과 (콘솔 오류 0) |
| R4. 관리자 | 완료 — 4.5 중 그래프 편집기를 뺀 전부 (`pages/admin/`). 데이터 조회 8종 중 Canonical Schema · Baseline · Parameter KB · Response Outputs 와 Baseline 카드는 혜정 전처리(`preprocessing-ui.js`)를 옮긴 것. 머리의 전처리 갱신 · 상태 줄(새 API `preprocessing/status`). 화면 데이터 응답 모델 전부. 저장 동작은 Playwright 로 임시 data 에서, 실제 서버에서는 읽기만 (콘솔 오류 0). vitest 65 · Playwright 8 |
| R5. 그래프 편집기 | 대기 |
| R6. 바꾸기 | 대기 |
