# AGENTS.md — test_auto_project

> 초안 (2026-10-15, 권지은). **3. 역할 경계 · 7. 용어집은 문혜정 확인 전.**
> 코딩 에이전트(Claude Code · Codex 등)가 작업 전에 읽는 안내서다. 코드로 알 수 있는 내용은 적지 않는다.

## 1. 프로젝트

자연어 요청으로 개발 서버에 테스트 데이터를 만드는 **테스트 데이터 생성기**.
예) "결제는 완료됐지만 출고는 안 된 주문 2건 만들어줘"

- 방식: **오프라인 구조** — 상태 전이 그래프를 미리 만들어 두고, 요청이 오면 그래프 위에서 경로를 계산한다.
- 현재 단계: **1차 (1.5주)** — API 구조 · 파라미터 데이터 기반 구축 + 상태 그래프. 2차는 자연어 → Scenario IR 통합.
- 팀: 권지은 · 문혜정. 저장소 `csmoon1010/kosa-2026-hyundai-project`, 이 폴더만 이 프로젝트다.

## 2. 정해진 설계 결정 (바꾸지 말 것 — 바꿔야 하면 먼저 묻는다)

1. **LLM 은 목표 상태만 뽑는다.** 호출 순서는 LLM 이 아니라 그래프 탐색(BFS)이 정한다. 같은 요청은 항상 같은 경로.
2. **간선은 API 후보 목록을 가진다.** 시나리오 등록 때 Agent 가 후보 중 하나를 고르고,
   그 결과는 **확인 후 저장(승인본)에 고정**한다. 실행 때 다시 고르지 않는다.
3. 승인본에는 경로 · 선택된 API · 파라미터 · 명세 spec_hash 를 남긴다. 달라지면 **재승인 필요**.
4. 파라미터 우선순위 (위가 이긴다):
   `실행 시 바꾼 값 > 자연어 > 앞 호출 응답 > 조회 · 파생 > 규칙(간선 > 도메인 > 전역) > Baseline > 생성`
5. 고정 규칙 — 설정으로 바꿀 수 없게 둔다: **쓰기 API = 재시도 0 · 승인 필요**, 조회 API = 재시도 2.
   쓰기 API 의 되돌림 불가 기본값은 `미확인` (사람이 확인해야 `가능`/`불가`).
6. 런타임 구조(요청마다 API 를 단계별 탐색)는 **폐기**했다. 다시 제안하지 않는다.
7. 입력 명세 `data/specs/hmall-openapi.json` 은 **외부 공개 명세(임시)** 다. 내부 명세로 교체될 예정이므로
   특정 명세에 묶인 코드를 짜지 않는다 — 명세마다 다른 것은 `data/config/*.yaml` 로 뺀다.
   공개 명세의 공백(예: 주문 생성 API 없음)은 문제 삼지 않는다.

## 3. 역할 경계 (확인 전)

| 담당 | 1단계 사전 작업 | 2단계 시나리오 등록 | 모듈 |
|---|---|---|---|
| 권지은 | 명세 파싱, API ID · 도메인 분류, API Catalog · MetaData, Tool Registry, State Vocabulary, State Graph Builder/Validator | 목표 상태 · 제약 추출(LLM), 업무 지식 조회(RAG), 경로 탐색, 경로 검증 | `spec/` `catalog/` `registry/` `states/`(예정) `graph/`(예정) |
| 문혜정 | Canonical Schema, Baseline Request, Parameter KB, Response Outputs | API 선택(Agent), 파라미터 매핑, 앞 호출 응답 바인딩, Scenario IR | (예정) |

- `src/tap/models.py` 는 **공용 기준**이다. 필드를 바꾸면 상대 작업이 깨지므로 한쪽에서 마음대로 바꾸지 않는다.
- `data/out/api_operations.json` 은 Canonical Schema 변환의 입력이다. 형식을 바꾸면 알린다.
- 간선 ↔ API 후보 형식(Graph Builder 출력 = Agent 입력)이 두 사람이 처음 맞물리는 지점이다.

## 4. 실행

```bash
cd test_auto_project
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt   # 시스템에 python3-venv 가 없어 uv 를 쓴다
PYTHONPATH=src .venv/bin/python -m tap.cli build    # data/out/ 산출물 생성
.venv/bin/python -m pytest -q                        # 전부 통과해야 커밋
```

- Python 3.10. LLM 은 OpenAI — 키와 모델 이름은 `.env`(`OPENAI_API_KEY`, `OPENAI_DEFAULT_MODEL` …)에서 읽고 코드에 박지 않는다.

## 5. 코드 규칙

- 분류 규칙 · 연결 설정 · 코드값처럼 **사람이 고칠 수 있는 값은 코드가 아니라 `data/config/*.yaml`** 에 둔다.
- LLM 결과에는 **원문 근거(인용 구절 · 출처)와 신뢰도(높음/중간/낮음)** 를 반드시 남긴다. 근거가 없으면 버린다.
  낮음은 지우지 말고 `review_queue.json` 같은 검수 대상으로 보낸다.
- 자동 산출물과 사람 보정은 섞지 않는다 — 보정은 별도로 쌓아 자동 재생성 때 지워지지 않게 한다.
- 테스트는 **네트워크 · LLM 없이** 돌아가야 한다 (LLM 부분은 고정 응답으로 대체).
- 문서 · 주석 · 커밋 메시지는 한국어, 식별자는 영어.

## 6. 하지 말 것

- `test_auto_project/` 밖(`JiEun/` `hyejung/` `mini_project_1/`)을 수정하지 않는다.
- `.env`, 인증 값(oauserId · oauseKey 의 실제 값), `.venv/` 를 커밋하지 않는다. 설정 파일에는 헤더 **이름**만 적는다.
- 커밋 · 푸시는 요청받았을 때만. 메시지 형식: `test_auto_project: 무엇을 했는지`.
- `prototype/offline-ui.html` 은 요청 없이 고치지 않는다 (UI 는 나중에 논의).

## 7. 용어집 (확인 전)

| 용어 | 뜻 |
|---|---|
| 상태 | 엔티티가 있을 수 있는 업무 상태. 그래프의 **노드** |
| 상태 후보 | 문서 · 명세에서 뽑은 정제 전 상태 표현. 근거 · 신뢰도를 가진다 |
| State Vocabulary | 확정된 상태 사전 — 상태명 · 코드 · 단계 · 종료 여부 · 동의어 · 조회 수단 · 도달/부재 검증 |
| 간선 | 상태 하나를 만드는 전이. 전제 상태 → 효과 상태, **API 후보 목록**을 가진다 |
| 목표 | 자연어에서 뽑은 도달할 상태 + "…아님" 조건 + 건수 (화면에서는 도달/제외 대신 '목표') |
| 경로 | 목표에 도달하는 간선의 순서. BFS 로 계산 |
| 승인본 | 등록 화면에서 "확인 후 저장"한 계획의 스냅샷 (버전 vN) |
| 재승인 필요 | 승인본과 현재 계산이 달라진 상태. 사유: 명세 변경 · 경로 변경 · 파라미터 변경 · 되돌림 불가 추가 |
| 규칙 | 사람이 입력한 기본값 · 조건부 필수 등. 범위: 간선 > 도메인 > 전역 |
| 조회 / 파생 / 생성 | 다른 값으로 DB·API 에서 찾음 / 다른 값으로 계산 / 시드 고정 가짜 값 |
| 앞 호출 응답 | 같은 실행 안에서 앞 API 가 돌려준 값 (예: order_id) |
| 되돌림 불가 | 외부 전송 등으로 롤백할 수 없는 쓰기 API |
| 쓰기 / 조회 | API 성격. Hmall 명세는 모두 POST 라 operationId 동사와 summary 로 판별 |
| 도메인 | product 상품 · vendor 협력사 · logistics 물류 · store 매장 · sales 실적 |
| Scenario IR | 등록 결과를 담는 JSON (경로 · 선택된 API · 파라미터 매핑). 2차 산출물 |

## 8. 열려 있는 결정 (에이전트가 임의로 확정하지 않는다)

- 상태 후보 추출에 쓸 **도메인 문서** — 아직 미제공.
- **Baseline Request · Response Outputs** 의 입력 · 검증 방식 — 검토 중.
- 상태 후보와 State Vocabulary 를 한 모델(`status: 후보|확정|버림`)로 둘지.
- `data/out/` 산출물을 커밋할지.
- UI 반영 시점.
