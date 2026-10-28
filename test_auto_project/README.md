# test_auto_project — 테스트 데이터 생성기

자연어로 요청하면 개발 서버에 테스트 데이터를 만들어 주는 도구입니다.

> 예) "결제는 완료됐지만 출고는 안 된 주문 2건 만들어줘"

## 방식 — 오프라인구조

상태 전이 그래프를 **미리 만들어 두고**, 요청이 오면 그래프 위에서 경로를 계산합니다.

1. LLM은 자연어에서 **목표 상태**만 뽑습니다 (`목표: 결제완료, 출고지시 아님, 2건`).
2. 호출 순서는 LLM이 아니라 **그래프 탐색(BFS)** 이 정합니다. 같은 요청은 항상 같은 경로가 나옵니다.
3. 각 단계의 API 인자는 우선순위대로 조합합니다.
   실행 시 바꾼 값 > 자연어 > 앞 호출 응답 > 조회 · 파생 > 규칙 > Baseline > 생성
4. 시나리오는 등록할 때 계획을 확인하고 저장하며(승인), 실행 메뉴에서는 저장된 시나리오를 골라 실행만 합니다.
   여러 시나리오를 묶어 실행하고, 하나라도 실패하면 전체를 실행 역순으로 되돌립니다.

## 구성

```
test_auto_project/
├── README.md
├── requirements.txt
├── prototype/
│   ├── offline-ui.html          # 화면 프로토타입 — 구현된 영역은 실제 산출물로 그림
│   ├── graph-editor.html        # 상태 그래프 만들기 (단독 화면)
│   ├── graph-editor.js          # 상태 그래프 편집기 본체 — 두 화면이 같이 씀
│   └── tap-data.js              # 실제 산출물 묶음 (tap.cli ui-data 로 생성)
├── data/
│   ├── specs/hmall-openapi.json # 입력 — HSHOP OPEN API (협력사용, OpenAPI 3.0.1, 42개 — /om 은 제외)
│   ├── config/
│   │   ├── domains.yaml         # 도메인 분류 규칙 (도메인 → prefix 여러 개, prefix 는 도메인 하나)
│   │   ├── services.yaml        # 도메인별 연결 설정 (base URL 환경변수 · timeout · 인증 · 허용 환경)
│   │   └── overrides.yaml       # 사람 보정 (설명 · 별칭 · 되돌림 불가 · 구별 메모 · 사용 여부 · 구분값) — 재생성해도 유지
│   └── out/                     # 산출물 (아래)
├── src/tap/
│   ├── models.py                # 산출물 데이터 모델 — 지은 · 혜정 공용 기준
│   ├── spec/parser.py           # OpenAPI 파싱 (XML Dataset 펼치기, example 해석)
│   ├── catalog/build.py         # API ID · 도메인 분류, Catalog · MetaData
│   ├── registry/tools.py        # Tool Registry
│   ├── graph/                   # 상태 그래프 — 모델 · 검증 · 경로 계산 · 재료 추출(실험) · API 후보 찾기(match)
│   ├── goal/ · ir/              # 목표 추출(LLM) · Scenario IR 초안
│   ├── ui/                      # 오프라인 UI 데이터 내보내기 · 로컬 서버
│   └── cli.py                   # 실행기
└── tests/
```

## 개발

```bash
cd test_auto_project
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
PYTHONPATH=src .venv/bin/python -m tap.cli build      # data/out/ 생성
PYTHONPATH=src .venv/bin/python -m tap.cli plan "출고된 주문 1건 만들어줘."   # 자연어 → 목표 → 경로 → Scenario IR (data/out/ir/)
PYTHONPATH=src .venv/bin/python -m tap.cli extract-graph --runs 2     # (실험) 공통코드 + 명세만으로 그래프 재료 추출 → 정답지와 채점
PYTHONPATH=src .venv/bin/python -m tap.cli match-graph               # 화살표 이름 · 상태만으로 API 후보 찾기 → 정답지와 채점
PYTHONPATH=src .venv/bin/python -m tap.cli serve                     # 오프라인 UI + 실제 계산 → http://127.0.0.1:8765/
.venv/bin/python -m pytest -q
```

### 1단계 산출물 (`data/out/`)

세 문서는 모두 **`api_id` = `서비스:메서드:경로`** (예: `hshop-openapi:POST:/pd/pdb/multiItem.do`) 로 연결된다.
생성 순서: 파싱 → 도메인 · 쓰기/조회 분류 → Tool Registry → API Metadata → API Catalog

| 파일 | 내용 | 다음 사용처 |
|---|---|---|
| `api_operations.json` | 파싱 결과 — API별 헤더 · Dataset · 요청/응답 필드(한글 이름 · 타입 · 예시) | 혜정: Canonical Schema 변환 |
| `tool_registry.json` | 도메인별 연결 설정 + API별 도구 (PK `api_id`, 재시도 · 승인 고정 규칙, 성공 판단 규칙) | 실행기 |
| `api_metadata.json` | API 전체 메타정보 — 쓰기/조회 · 동작 · 별칭 · 구분값(selectors) · 되돌림 불가 · 구별 메모 · 출처 (Catalog 의 원본) | Agent API 선택 · 승인 화면 · 그래프 간선의 API 후보 찾기 |
| `api_catalog.json` | Agent 가 훑어보는 가벼운 목록 (Metadata 에서 복사, 내용이 바뀔 때만 버전 증가) | 경로 탐색 시 후보 좁히기 |
| `review_queue.json` | 규칙으로 확정하지 못한 항목 (도메인 미분류 · 성공 규칙 없음 등) | 사람 검수 |

### 한 바퀴 — 자연어 → Scenario IR (주문상태 그래프)

`data/knowledge/ord_stat.yaml`: 사람이 확인한 업무 지식 — 주문상태 코드(ORD_STAT_GBCD), 동작별 전이
(출고진행 P1 25→30 · 출고완료 P2 30→45 · 배송완료 P3 45→50, 취소 PB1~PB3), 상태별 조회 방법(출고조회 prgrGb P0~P3).

0. **그래프 고르기 (LLM)** — 사람이 확인한 그래프(data/knowledge) + 화면 저장본(data/out/graphs, 같은 id 는 저장본 우선) 중 요청에 맞는 것 하나. 없으면 거절.
1. **목표 추출 (LLM)** — 상태 이름 목록 안에서만 target · must_pass · count 를 고른다. 근거 구절이 원문에 없으면 버린다.
2. **경로 계산 (BFS)** — A 진행시키기(출고대기 25 주문을 찾아 API 로 진행, 기본) / B 찾아 쓰기(목표 상태를 바로 조회, 대안).
   API 로 만들 수도 조회로 찾을 수도 없는 상태(예: 결제완료 20)는 거절한다.
3. **Scenario IR (초안)** — 조회 → 쓰기(고정 선택값 + 앞 호출 응답 연결 + 되돌리기 간선) → 도달 확인.

### 실험 — 공통코드 + 명세만으로 그래프 재료를 만들 수 있나 (`extract-graph`)

입력은 `data/codes/common_codes.csv`(공통코드 테이블 export 형식) 와 1단계 산출물(명세 요약)뿐이다.
LLM 이 전이 · 조회 방법 · 상태 필드 · 진입 상태를 제안하고, `ord_stat.yaml`(사람이 확인한 정답지)과 비교한다.
결과는 `data/out/extract/` — 같은 그래프 형식이라 경로 계산까지 돌려 정답 그래프와 같은 호출 순서가 나오는지도 본다.

### 구분값 (API Metadata `selectors`)

한 API 가 여러 일을 할 때 이번 일을 고르는 요청 필드와 값 (예: `multiOshpProcess` 의 procGb P1 출고진행 · P2 출고완료 · P3 배송완료).
그래프 간선 = api_id + 구분값이고, API 에 대한 지식은 그래프가 아니라 Metadata 에 쌓는다 — 한 번 보정하면 모든 그래프가 같이 쓴다.

| 값 | 뜻 |
|---|---|
| `null` | 아직 판단 안 함 |
| `[]` | 구분값 없음 (API 하나가 동작 하나) — `selectors_source` 로 자동 판단(auto) / 사람 확인(override) 구분 |
| `[{field, complete, values}]` | 필드와 값 목록. `complete: false` 면 값이 더 있을 수 있어 검수 목록에 올린다 |

자동 추출: 예시값이 코드 모양(P1 · PB1)이거나 이름이 rowFlag · rowType 인 필드를 구분값 필드로 보고,
summary 의 '이름(값)' 이 둘 이상이면 값 목록 전부로 본다. 명세에 없는 값 · 다른 이름은 overrides.yaml 에서 보정한다
(이름을 고치면 명세 이름은 aliases 로 남는다). 그래프 검증은 간선 · 조회의 구분값이 Metadata 에 있는지 확인한다.

Hmall 명세는 모든 API 가 POST 라서 쓰기/조회를 HTTP 메서드가 아니라 operationId 동사(select · insert · update · multi)와
summary 의 한국어 동사로 판별한다.

## 프로토타입 보기

`prototype/offline-ui.html` 을 브라우저로 열면 됩니다. `tap-data.js` 가 옆에 있으면 구현된 영역을 실제 산출물로 그립니다
(`tap.cli ui-data` 로 다시 만든다). `tap.cli serve` 로 열면 아래 두 가지가 실제로 실행됩니다.

| 영역 | 파일로 열 때 | `tap.cli serve` 로 열 때 |
|---|---|---|
| 시나리오 생성 결과 | 미리 계산해 둔 문장(data/out/ir)만 실제 결과, 나머지는 시연 | 아무 문장이나 목표 추출(LLM) → 경로 → Scenario IR |
| 관리자 › 도메인 › 상태 그래프 만들기 | 실제 그래프 · 실제 Metadata 로 API 후보 찾기 | + 저장하면 data/out/graphs/ 에 파일로 (정답지 data/knowledge 는 그대로) |
| 데이터 조회 — Catalog · MetaData · Tool Registry · State Vocabulary | 실제 산출물 | 같음 (매번 새로 읽음) |
| 관리자 › 전사 › 1단계 산출물 · 검수 목록 | 실제 산출물 | 같음 |
| 관리자 › 규칙 입력 (API Catalog · MetaData · State Vocabulary · Parameter KB) | 실제 API · 상태 · 필드를 대상으로, 저장은 이 화면에만 | `data/config/rules.ui.yaml` 에 저장 → Catalog · MetaData 항목은 바로 다시 빌드해 반영 |
| 관리자 › Baseline Request | 실제 API, 명세 예시로 초안 | `data/baselines/<api>.json` 에 저장 (요청 필드에 없는 이름이면 거절) |
| 관리자 › 명세 소스 · 도메인별 현황 · 간선 레지스트리 · 거절 로그 · 환경 | 실제 산출물 | + '다시 빌드' 실행 |
| 시나리오 목록 · 확인 후 저장 | 실제 — 처음엔 비어 있음, 저장은 이 화면에만 | `data/scenarios/<id>.json` (Scenario IR 을 그대로 고정 = 승인본, catalog 버전이 바뀌면 재승인 필요) |
| 실행 · 이력 | **드라이런** — API 호출 없이 건별 호출 계획 · 되돌리는 순서 · 미해결 파라미터 | + `data/runs/<id>.json` 에 이력. 실제 실행은 실행기 연결 후 |

### 상태 그래프 만들기 — 업무 담당자는 상태와 화살표만

공통코드에서 상태를 끌어다 놓고, 상태의 ● 을 끌어 화살표를 잇고, 화살표에 **업무에서 부르는 이름**만 적는다.
API 는 그 이름으로 API Metadata(구분값 · 별칭 · API 이름)에서 시스템이 찾는다 (`src/tap/graph/match.py`, 화면은 같은 규칙의 JS).
못 찾았거나 애매한 화살표는 **개발 담당자 검수**로 넘어가고, 개발 담당자가 overrides.yaml 에 별칭 · 구분값을 보정하면 다시 찾는다.
최종 API 선택은 시나리오 등록 때 Agent 가 후보 중에서 하고 승인본에 고정한다.

**규칙 저장 구조**: 개발 담당자가 손으로 고치는 `overrides.yaml` 은 주석까지 그대로 두고, 화면에서 넣은 규칙은
`rules.ui.yaml` 에 쌓인다. 빌드할 때 화면 규칙 중 Catalog · MetaData 항목(설명 · 별칭 · 제외 · 되돌림 불가 · 구별 메모 · 구분값)을
overrides 위에 합친다. 잘못된 규칙이면 빌드가 거절하고 파일을 되돌린다. State Vocabulary 는 **동의어**만 받고, 시나리오 생성 때
목표 추출(LLM)에 상태 목록과 함께 보여 준다 (`- 배송완료 (50) · 다른 표현: 초록불`). Parameter KB 규칙은 저장만 한다 (쓰는 단계는 아직 없음).

**진입 상태 · 조회 방법은 화면에서 정하지 않는다**: 기본 방식(진행시키기)은 조회로 찾을 수 있고 목표까지 갈 수 있는 상태 중
공통코드 정렬순서가 가장 앞인 상태에서 출발한다. 조회 API 는 화살표 API 처럼 자동 후보로 두고 고르는 건 시나리오 등록 때 Agent 가 한다.
캔버스에 놓지 않은 상태(예: 결제완료)도 코드 목록에는 남아, 그 상태를 고른 요청은 이유와 함께 거절된다.

**새 그래프**: 공통코드 테이블(`data/codes/common_codes.csv`)에 있는데 아직 그래프가 없는 그룹을 골라 빈 캔버스에서 시작한다.
상태 필드는 코드 그룹 ID 를 낙타 표기로 바꾼 응답 필드에서 추정한다 (SLITM_APRVL_GBCD → slitmAprvlGbcd).
서버로 열고 저장하면 `data/out/graphs/<그룹ID>.yaml` 에 쓰고, 다음에 열 때 그 저장본(배치 · 화살표 · 외부 변화)으로 다시 연다.

- 화면: 시나리오 등록 · 시나리오 실행 · 실행 이력 · 관리자 메뉴(전사 / 도메인)
- 데이터는 시연용으로 심어 둔 값이며 실제 API를 호출하지 않습니다.
- 사이드 메뉴 아래 **시연 모드** 를 켜면 실행 실패 · 롤백을 재현할 수 있습니다.

## 관리 문서 (8종)

| 문서 | 내용 | 채우는 방식 |
|---|---|---|
| API Catalog | 엔드포인트와 한 줄 설명 | Swagger 자동 + 도메인 보정 |
| API MetaData | 쓰기/조회, 되돌림 불가, 구별 메모 | Swagger 자동 + 도메인 보정 |
| Canonical Schema | 정규화한 요청 필드 · 타입 | Swagger 자동 (수정 불가) |
| Tool Registry | 서비스별 timeout · 인증 | Swagger 등록 시 입력 (전사) |
| Baseline Request | 실제로 성공한 요청 전문 | 도메인 등록 |
| Parameter KB | 필드 의미 · 별칭 · 값 해석 · 기본값 · 조건부 필수 | 자동 + 전사 · 도메인 보정 |
| Response Outputs | 응답에서 꺼내 다음 호출에 넘기는 값 | 자동 + 도메인 보정 |
| State Vocabulary | 그래프 노드가 되는 상태 · 동의어 · 검증 | 자동 + 도메인 보정 |

> 현재 입력 명세는 **외부 공개 OpenAPI**(HSHOP OPEN API)다. 내부 API 명세는 보안 문제로 아직 반출 전이며,
> 받으면 `data/specs/` 의 명세와 `data/config/` 설정만 교체한다.

## 상태

화면 프로토타입 단계입니다. Baseline Request · Response Outputs 의 입력 방식은 아직 검토 중입니다.
