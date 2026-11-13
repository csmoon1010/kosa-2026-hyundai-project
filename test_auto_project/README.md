# 테스트 데이터 생성기

자연어로 요청하면 개발 서버에 테스트 데이터를 만드는 시나리오를 만들어 주는 도구입니다.

> 예) "001442 협력사코드의 주문 한건을 배송완료까지 처리해줘"
> → 출고대기 주문 찾기 → 출고진행 → 출고완료 → 배송완료 (단계마다 API · 입력값이 정해진 시나리오)

## 어떻게 동작하나

```
자연어 요청
  → ① 요청 이해     업무 목록 (도메인 · 신규/기존 · 건수 · 조건)                LLM
  → ② 경로 찾기     업무마다 상태 그래프 위의 출발 → 목표 상태와 경로             LLM(상태 고르기) + 그래프 탐색(코드)
  → ③ API 고르기    경로의 단계마다 API · 구분값                                 규칙(코드) · 애매할 때만 LLM
  → 시나리오 생성   단계마다 입력값 · 앞 단계 결과 넘기기 (Scenario IR)          LLM 에이전트 (Baseline · Parameter KB)
  → 승인 · 등록     사람이 확인하고 승인 — 승인본 고정
  → 실행            등록 시나리오 실행 (지금은 드라이런 — 실제 API 는 부르지 않음)
```

- **호출 순서는 LLM 이 아니라 그래프 탐색이 정합니다.** 그래프에 없는 화살표는 나올 수 없고, 같은 요청은 같은 경로가 나옵니다.
- **API 는 규칙으로 먼저 고르고, 후보가 비슷할 때만 LLM 이 후보 안에서 고릅니다.** 확신이 없으면 '가선택'으로 남겨 사람이 확인합니다.
- **권한 등급과 승인은 코드가 정합니다.** 되돌릴 수 없는 단계(R2)는 실행할 때마다 다시 확인하고, 범위 밖(R3)은 승인으로도 열 수 없습니다.
- 요청 속 지시문(프롬프트 인젝션)은 ① 직후 감지해 요청 전체를 차단합니다.

자세한 구조는 [docs/architecture.md](docs/architecture.md), API 선택 규칙은 [docs/api-selection-rule.md](docs/api-selection-rule.md),
평가는 [docs/evaluation.md](docs/evaluation.md) 에 있습니다.

## 화면

`tap.cli serve` 로 띄운 로컬 서버에서 씁니다. 화면은 React(`frontend/`)로 만들어 빌드한 것을 서버가 내려줍니다.

| 메뉴 | 하는 일 |
|---|---|
| **시나리오 등록** | 이름 · 자연어 요청 입력 → 분석(진행 표시) → 시나리오 미리보기(업무 · 단계 · 입력값 표) → 확인할 것 체크 → 승인하고 등록 |
| **시나리오 실행** | 등록 시나리오 고르기 · 반복 횟수 → 되돌릴 수 없는 단계 확인 → 드라이런(단계별 입력값 · 보낼 요청 XML) |
| **실행 이력** | 드라이런 기록 |
| **시나리오 등록(확인용)** | 중간 과정을 모두 보여 주는 화면 — ①②③ 결과 · 후보 · 점수 · 트레이스 · 승인 게이트 · IR 생성 과정 |
| **관리자 메뉴** | 상태 그래프 그리기 · API Catalog / Metadata 보정 규칙 · Baseline Request · 명세 다시 빌드 · 전처리 산출물 |

## 시작하기

Python 3.10, [uv](https://docs.astral.sh/uv/) 를 씁니다.

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
cp .env.example .env            # OPENAI_API_KEY · OPENAI_DEFAULT_MODEL · OPENAI_EMBEDDING_MODEL 을 채운다
(cd frontend && npm ci && npm run build)   # 화면 빌드 → frontend/dist (Node 20 이상, 화면을 고쳤을 때마다)
.venv/bin/python -m tap.cli serve      # → http://127.0.0.1:8765/
```

화면을 빌드하지 않고 띄우면 첫 화면에 빌드 명령을 안내합니다 (API 는 그대로). WSL 밖 브라우저에서 열리지 않으면 `--host 0.0.0.0` 을 붙입니다. 명세를 바꿨거나 `data/out/` 이 없으면 먼저 `tap.cli build` 를 실행합니다.

### 명령

```bash
.venv/bin/python -m tap.cli build        # 명세 → API Catalog · Metadata · Tool Registry (data/out/)
.venv/bin/python -m tap.cli intent "…"   # ① 업무 목록
.venv/bin/python -m tap.cli path   "…"   # ①② 업무마다 그래프 · 경로
.venv/bin/python -m tap.cli select "…"   # ①②③ 단계마다 API (트레이스: data/out/traces/)
.venv/bin/python -m tap.cli run    "…" --approve [--steps 1-0] [--confirm 1-1]   # 승인 → 실행 확인 → 드라이런
.venv/bin/python -m tap.cli eval-stages --runs 3   # 단계별 평가 (docs/evaluation.md)
.venv/bin/python -m tap.cli serve        # 화면 + 실제 계산 (FastAPI · API 목록 http://127.0.0.1:8765/api/docs)
.venv/bin/python -m pytest -q          # 서버 테스트 (LLM · 네트워크 없이)
cd frontend && npm test                  # 화면 테스트 (Vitest) · npm run test:e2e (Playwright, 가짜 LLM 서버)
cd frontend && npm run dev               # 화면 개발 (docs/react.md) → http://127.0.0.1:5173/ (/api 는 8765 서버로)
```

## 폴더

```
├── src/tap/
│   ├── spec/ catalog/ registry/   명세 파싱 · 도메인 · 쓰기/조회 분류 → API Catalog · Metadata · Tool Registry
│   ├── goal/extract.py            ① 업무 의도 분석 (LLM 호출 openai_parse 포함)
│   ├── graph/                     상태 그래프 모델 · 검증 · 경로 계산(plan) · ② 경로 탐색(paths) · 화살표→API 후보(match)
│   ├── apis/                      ③ API 선택(select) · 권한 등급 · 승인 게이트(gate)
│   ├── ir/                        승인본 → IR 입력(handoff) · Scenario IR 생성(draft_build, 혜정) · 단계 의존성 · XML 미리보기
│   ├── agent/ retrieval/          IR 생성 에이전트 (도구 · 예산 · 검증 · 재시도 · 문맥 압축 · Parameter KB 검색)
│   ├── api/                       서버 — FastAPI 앱 · 메뉴별 라우터(register · inspect · run · history · admin · common) · 처리 로직(services) · 요청 · 응답 모델(models)
│   ├── ui/                        화면 데이터(export) · 전처리 산출물 조회(preprocessing)
│   ├── trace.py                   LLM 호출 기록 · 예산 · 중지 조건
│   ├── eval_stages.py             단계별 평가
│   └── cli.py
├── frontend/                      화면 — React · Vite · TypeScript (docs/react.md). 빌드 결과 frontend/dist 를 서버가 내려준다
│   ├── src/pages/                 메뉴별 화면 — register · inspect(+ 혜정 IR 영역) · run · history · admin(+ 상태 그래프 편집기 · 전처리 산출물)
│   ├── src/api/                   서버 호출 · 진행 스트림 · 타입(schema.d.ts — /api/openapi.json 에서 생성)
│   └── e2e/                       Playwright (가짜 LLM 서버를 직접 띄운다)
├── data/
│   ├── specs/                     입력 명세 (HSHOP OPEN API, 공개 OpenAPI 3.0.1 — 내부 명세로 바뀔 예정)
│   ├── config/                    사람이 고치는 설정 — 도메인 · 연결 · 보정(overrides) · 권한 등급 · LLM 예산
│   ├── graphs/                    상태 그래프 (주문상태 · 판매상품승인 · 상품가격승인)
│   ├── codes/                     공통코드 표 (그래프 상태 이름)
│   ├── golden/                    정답 그래프 (테스트 · 채점용 고정본)
│   ├── eval/stage_gold.json       단계별 정답셋
│   └── out/                       산출물 — API 문서 · parameters/(Parameter KB · Baseline · 스키마 · 응답 출력 · 벡터 인덱스)
├── docs/                          구조 · 선택 규칙 · 평가 · scenario-ir*(IR 생성 설계 · 검증)
├── scripts/                       IR 생성 압축 평가 스크립트 (실제 API 호출 — 비용 있음)
├── tests/                         pytest, fixtures/(IR 입력 기준 예제) — 화면 테스트는 frontend/ 안 (Vitest · Playwright)
└── pyproject.toml                 패키지 · 의존성(버전 고정) · pytest 설정
```

실행할 때 생기는 파일은 저장소에 넣지 않습니다 — `data/registered/`(등록) · `data/runs/`(실행 이력) · `data/approved/`(확인용 승인 기록) ·
`data/ir_inputs/`(IR 입력 승인본 · 검토 초안) · `data/out/traces/` · IR 초안 · 로그 · `frontend/dist`(화면 빌드 결과).

## 한계

- **실제 실행은 아직 없습니다.** 실행 메뉴는 드라이런 — 실행기와 개발 서버 인증이 연결되면 붙입니다.
- **입력 명세는 외부 공개 명세(임시)입니다.** 공개 명세에 없는 API(예: 주문 생성)는 고를 수 없습니다. 내부 명세를 받으면 `data/specs/` 와 `data/config/` 만 바꿉니다.
- 1차 범위는 상품(pd) · 주문(od) · 물류(ds) 도메인입니다. 다른 도메인 요청은 차단됩니다.

## 팀

권지은 — ①②③ · 그래프 · 승인 게이트 · 화면 · 평가 / 문혜정 — 전처리(Parameter KB · Baseline · 스키마) · Scenario IR 생성 에이전트
