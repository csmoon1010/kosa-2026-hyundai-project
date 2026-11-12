# AGENTS.md

코딩 에이전트(Claude Code · Codex 등)가 작업 전에 읽는 안내서다. 코드로 알 수 있는 내용은 적지 않는다.
구조는 [docs/architecture.md](docs/architecture.md), API 선택 규칙은 [docs/api-selection-rule.md](docs/api-selection-rule.md).

## 1. 프로젝트

자연어 요청으로 개발 서버에 테스트 데이터를 만드는 시나리오를 만들고 실행하는 **테스트 데이터 생성기**.
팀: 권지은(①②③ · 그래프 · 승인 게이트 · 화면 · 평가), 문혜정(전처리 · Scenario IR 생성 에이전트).

## 2. 정해진 설계 결정 — 바꿔야 하면 먼저 묻는다

1. **호출 순서는 그래프 탐색이 정한다.** LLM 은 업무 · 그래프 · 상태를 이름으로 고를 뿐 경로를 쓰지 않는다.
2. **그래프는 노드 흐름만 갖는다.** API 는 그래프에 적지 않고 ③ 이 API Metadata 에서 고른다. API 에 대한 지식(별칭 · 구분값)은 Metadata 에 쌓는다.
3. **API 는 규칙이 먼저, LLM 은 비슷한 후보 사이에서만** 고른다. 확신이 없으면 가선택으로 남겨 사람이 확인한다.
4. **권한 등급 · 승인은 코드가 정한다.** LLM 이나 요청 문장으로 바꿀 수 없다. R2 는 실행할 때마다 확인, R3 는 차단.
5. **승인은 선택 결과 해시에 묶인다.** 등록 뒤에는 다시 고르지 않는다. API Catalog 가 바뀌면 재승인.
6. **요청마다 API 를 단계별로 탐색하는 런타임 구조는 폐기했다.** 다시 제안하지 않는다.
7. 입력 명세 `data/specs/hmall-openapi.json` 은 **외부 공개 명세(임시)** 다. 특정 명세에 묶인 코드를 짜지 않는다 — 명세마다 다른 것은 `data/config/*.yaml` 로 뺀다. 공개 명세의 공백(예: 주문 생성 API 없음)은 문제 삼지 않는다.

## 3. 실행

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"   # 시스템에 python3-venv 가 없어 uv 를 쓴다
.venv/bin/python -m tap.cli serve      # 화면 → http://127.0.0.1:8765/
.venv/bin/python -m pytest -q && node --test tests/*.cjs   # 전부 통과해야 커밋
cd frontend && npm ci && npm run typecheck && npm run lint && npm test   # React 화면(옮기는 중) — 고쳤으면 이것도 통과해야 커밋
cd frontend && npm run test:e2e          # 화면 끝까지 (Playwright, 가짜 LLM 서버를 직접 띄움 — 비용 없음)
```

- Python 3.10. LLM 은 OpenAI — 키 · 모델 이름은 `.env`(`.env.example` 참고)에서 읽고 코드에 박지 않는다.
- 서버는 FastAPI(`src/tap/api/`) — 경로 · 오류 형식 · 스트리밍 · 라우터 작성 규칙은 [docs/fastapi.md](docs/fastapi.md). API 목록은 서버의 `/api/docs`.
- 서버는 Python 코드를 시작할 때 읽는다. Python 을 고쳤으면 서버를 다시 띄운다 (화면 파일은 새로고침만).
- 화면을 React(`frontend/`)로 옮기는 중 — 기준 문서는 [docs/react.md](docs/react.md). 개발은 `npm run dev`(5173, `/api` 는 8765 로). 서버 요청 · 응답 모델(`src/tap/api/models.py`)을 바꾸면 `npm run gen:api` 로 `src/api/schema.d.ts` 를 다시 만들어 같은 커밋에.

## 4. 코드 규칙

- 분류 규칙 · 연결 설정 · 권한 등급 · 예산처럼 **사람이 고칠 수 있는 값은 `data/config/*.yaml`** 에 둔다.
- LLM 결과에는 **원문 근거(인용 구절)** 를 남기고 코드로 다시 확인한다. 근거가 원문에 없으면 버린다.
- 자동 산출물과 사람 보정은 섞지 않는다 — 보정은 `overrides.yaml` · `rules.ui.yaml` 에 따로 쌓는다.
- 테스트는 **네트워크 · LLM 없이** 돌아가야 한다 (LLM 은 고정 응답으로 대체). 저장소 파일을 고쳐 쓰는 테스트는 임시 복사본을 쓴다.
- 문서 · 주석 · 커밋 메시지는 한국어, 식별자는 영어.
- `src/tap/models.py` · `data/out/api_operations.json` · IR 입력 형식(`ir/handoff.py`)은 두 사람이 맞물리는 지점이다. 형식을 바꾸면 알린다.

## 5. 하지 말 것

- `.env`, 인증 값(oauserId · oauseKey 의 실제 값), `.venv/` 를 커밋하지 않는다. 설정 파일에는 헤더 **이름**만 적는다.
- 실행할 때 생기는 파일(`data/registered/` · `data/runs/` · 트레이스 · IR 초안 · 로그)을 커밋하지 않는다 (`.gitignore`).
- `data/out/parameters/parameter_vectors/` 는 고정본이다 — 다시 만들려면 임베딩 비용이 든다.
- 커밋 · 푸시는 요청받았을 때만.

## 6. 용어

| 용어 | 뜻 |
|---|---|
| 업무 | ① 이 나눈 요청 단위. 도메인 · 신규/기존 · 건수 · 조건(대상조건 / 설정값) |
| 상태 그래프 | 상태 코드 그룹 하나의 상태(노드)와 화살표(업무 이름). `data/graphs/` |
| 경로 | 출발 상태에서 목표 상태까지 거치는 화살표 순서 |
| 구분값 | 한 API 가 여러 일을 할 때 이번 일을 고르는 요청 필드와 값 (`procGb=P1`) |
| 선택 / 가선택 / 보류 | ③ 결과 — 그대로 씀 / 사람 확인 필요 / 고를 API 없음 |
| 참조 조회 | 쓰기에 넣을 코드를 이름으로 찾는 조회 단계 (브랜드명 → 브랜드코드) |
| 행 상태값 | `rowType` · `rowFlag` — 업무 동작(생성 · 수정 · 삭제)으로 채운다 |
| R0 ~ R3 | 권한 등급 — 조회 / 되돌릴 수 있는 쓰기 / 되돌릴 수 없는 쓰기 / 금지 |
| 검토 초안 | 승인 전에 IR 을 만들기 위한 입력 (`approval_status: review`) |
| Scenario IR | 단계마다 API · 입력값(고정값 · 앞 단계 값) · 결과 넘기기를 담은 시나리오 |
| 등록 시나리오 | 승인한 분석 결과 · 게이트 · IR 을 한 파일로 고정한 것 (`data/registered/`) |
| 드라이런 | API 를 부르지 않고 보낼 요청만 만드는 실행 |

## 7. 열려 있는 일

- 실행기(실제 API 호출)와 개발 서버 인증 연결.
- 내부 명세 · 도메인 문서 반영 — 정답셋의 판단 보류 항목 확인.
- `web/offline-ui.html` 의 시연 데이터 모드(서버 없이 보는 가짜 데이터) 정리 — 확인용 · 관리자 화면이 같은 함수를 써서 따로 다룬다.
- 그래프 없는 대상 조회의 점수 개선 ([api-selection-rule.md](docs/api-selection-rule.md#5-기준값과-근거)).
