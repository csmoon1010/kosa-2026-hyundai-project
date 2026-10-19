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
│   └── offline-ui.html          # 화면 프로토타입 (브라우저에서 바로 열림)
├── data/
│   ├── specs/hmall-openapi.json # 입력 — HSHOP OPEN API (협력사용, OpenAPI 3.0.1, 43개)
│   ├── config/
│   │   ├── domains.yaml         # 도메인 분류 규칙 (도메인 → prefix 여러 개, prefix 는 도메인 하나)
│   │   ├── services.yaml        # 도메인별 연결 설정 (base URL 환경변수 · timeout · 인증 · 허용 환경)
│   │   └── overrides.yaml       # 사람 보정 (설명 · 별칭 · 되돌림 불가 · 구별 메모 · 사용 여부) — 재생성해도 유지
│   └── out/                     # 산출물 (아래)
├── src/tap/
│   ├── models.py                # 산출물 데이터 모델 — 지은 · 혜정 공용 기준
│   ├── spec/parser.py           # OpenAPI 파싱 (XML Dataset 펼치기, example 해석)
│   ├── catalog/build.py         # API ID · 도메인 분류, Catalog · MetaData
│   ├── registry/tools.py        # Tool Registry
│   └── cli.py                   # 실행기
└── tests/
```

## 개발

```bash
cd test_auto_project
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
PYTHONPATH=src .venv/bin/python -m tap.cli build      # data/out/ 생성
.venv/bin/python -m pytest -q
```

### 1단계 산출물 (`data/out/`)

세 문서는 모두 **`api_id` = `서비스:메서드:경로`** (예: `hshop-openapi:POST:/pd/pdb/multiItem.do`) 로 연결된다.
생성 순서: 파싱 → 도메인 · 쓰기/조회 분류 → Tool Registry → API Metadata → API Catalog

| 파일 | 내용 | 다음 사용처 |
|---|---|---|
| `api_operations.json` | 파싱 결과 — API별 헤더 · Dataset · 요청/응답 필드(한글 이름 · 타입 · 예시) | 혜정: Canonical Schema 변환 |
| `tool_registry.json` | 도메인별 연결 설정 + API별 도구 (PK `api_id`, 재시도 · 승인 고정 규칙, 성공 판단 규칙) | 실행기 |
| `api_metadata.json` | API 전체 메타정보 — 쓰기/조회 · 동작 · 별칭 · 되돌림 불가 · 구별 메모 · 출처 (Catalog 의 원본) | Agent API 선택 · 승인 화면 |
| `api_catalog.json` | Agent 가 훑어보는 가벼운 목록 (Metadata 에서 복사, 내용이 바뀔 때만 버전 증가) | 경로 탐색 시 후보 좁히기 |
| `review_queue.json` | 규칙으로 확정하지 못한 항목 (도메인 미분류 · 성공 규칙 없음 등) | 사람 검수 |

Hmall 명세는 모든 API 가 POST 라서 쓰기/조회를 HTTP 메서드가 아니라 operationId 동사(select · insert · update · multi)와
summary 의 한국어 동사로 판별한다.

## 프로토타입 보기

`prototype/offline-ui.html` 을 브라우저로 열면 됩니다. 별도 서버나 설치가 필요 없습니다.

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
