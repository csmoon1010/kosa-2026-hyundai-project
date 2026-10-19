"""산출물 데이터 모델.

지은(API 구조 · 업무 흐름)과 혜정(개별 API 데이터 · 파라미터)이 함께 쓰는 기준이다.
파싱 결과(ApiOperation)는 혜정의 Canonical Schema 변환 입력이 되므로,
필드를 바꿀 때는 양쪽이 합의한다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ----------------------------------------------------------------- 파싱 결과


class ApiField(BaseModel):
    """요청 · 응답 본문의 말단 필드(컬럼) 하나."""

    name: str                                   # 컬럼 이름 (예: procGb)
    path: str                                   # 본문 안 위치 (예: data1/data2/data3/procGb)
    dataset_id: str | None = None               # 소속 Dataset 의 id (예: dsInput)
    label: str | None = None                    # 한글 이름 (예: 진행구분코드)
    type: str | None = None                     # 명세상 타입 (예: string)
    example: str | None = None                  # 예시 값 (예: P1)
    required: bool = False
    raw_example: str | None = None              # 명세 원문 — 해석이 틀렸을 때 확인용


class ApiHeader(BaseModel):
    name: str
    required: bool = False
    description: str | None = None


class ApiOperation(BaseModel):
    """OpenAPI 의 operation 하나를 정규화한 것. 이후 모든 산출물의 출발점."""

    api_id: str                                 # 프로젝트 안에서 쓰는 고유 ID
    method: str                                 # POST, GET …
    path: str                                   # /pd/pdb/multiItem.do
    operation_id: str | None = None
    summary: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    request_content_type: str | None = None     # application/xml …
    headers: list[ApiHeader] = Field(default_factory=list)
    request_datasets: list[str] = Field(default_factory=list)   # 요청 Dataset id 목록
    dataset_notes: dict[str, str] = Field(default_factory=dict)  # Dataset 이름에 붙은 메모 (조건부 입력 등)
    request_fields: list[ApiField] = Field(default_factory=list)
    response_fields: list[ApiField] = Field(default_factory=list)
    spec_source: str                            # 명세 파일 이름 = document_id
    service: str                                # 서비스 이름 — api_id 앞부분

# ------------------------------------------------------------------- 공통

Confidence = Literal["높음", "중간", "낮음"]
ApiKind = Literal["read", "write"]
Irreversible = Literal["미확인", "가능", "불가"]


class DomainGuess(BaseModel):
    domain: str                                 # pd, ds …
    confidence: Confidence
    reason: str                                 # 어떤 규칙으로 정했는지

# ------------------------------------------------------------------ API Metadata


class ApiMetaData(BaseModel):
    """API 의 전체 검색 · 실행 메타정보. Catalog 의 원본이다.

    description · aliases · irreversible · memo 는 사람 보정(data/config/overrides.yaml)이 덮어쓴다.
    """

    # identity
    api_id: str                                 # hshop-openapi:POST:/pd/pdb/multiItem.do
    api_name: str                               # 명세 summary
    domain: str                                 # pd — domains.yaml prefix 규칙
    kind: ApiKind                               # 쓰기/조회 — 모든 API 가 POST 라 동사로 판별
    action: str                                 # 조회 · 등록 · 수정 · 요청 · 처리 …
    metadata_version: int = 1                   # 내용이 바뀔 때만 올린다
    # description
    description: str | None = None              # api_name 과 같으면 비운다
    # knowledge
    aliases: list[str] = Field(default_factory=list)          # API 선택 시 참고하는 도움말
    input_concepts: list[str] = Field(default_factory=list)   # 1차 비움 — 2차에 Canonical Schema 에서 요약
    output_concepts: list[str] = Field(default_factory=list)  # 1차 비움 — 2차에 Response Outputs 에서 요약
    # safety
    irreversible: Irreversible = "미확인"       # 쓰기 API 기본값 — 사람이 확인해야 가능/불가
    memo: str | None = None                     # 구별 메모 — 간선의 후보끼리 구분
    # tool
    tool_enabled: bool = True                   # Tool Registry enabled 복사
    # search
    search_text: str = ""                       # operation_id + api_name + description + aliases + memo
    # source
    source_type: Literal["SWAGGER"] = "SWAGGER"
    document_id: str                            # 명세 파일 이름
    operation_id: str | None = None
    spec_hash: str                              # 명세 변경 → 재승인 판단

# ------------------------------------------------------------------- API Catalog


class ApiCatalogEntry(BaseModel):
    """Agent 가 후보를 고를 때 훑어보는 가벼운 목록. 값은 모두 API Metadata 에서 복사한다."""

    api_id: str
    operation_id: str | None = None
    api_name: str
    description: str | None = None
    domain: str
    kind: ApiKind
    aliases: list[str] = Field(default_factory=list)
    tool_enabled: bool = True


class SpecSource(BaseModel):
    service: str
    document_id: str                            # 명세 파일 이름
    spec_hash: str


class ApiCatalog(BaseModel):
    catalog_version: int                        # catalog_hash 가 바뀔 때만 올린다
    catalog_hash: str                           # 내용 지문 (generated_at 제외)
    generated_at: str
    spec_sources: list[SpecSource]
    apis: list[ApiCatalogEntry]

# ------------------------------------------------------------------ Tool Registry


AuthType = Literal["NONE", "API_KEY_HEADER", "OAUTH2"]


class ConnSettings(BaseModel):
    """도메인 단위 연결 설정 (도메인 설정 > 서비스 기본값 > 명세 추정). 사람이 services.yaml 에서 정한다."""

    service: str
    domain: str
    base_url: str                               # 환경변수 이름 (예: HMALL_API_BASE_URL) — 값은 .env
    base_url_default: str = ""                  # 환경변수가 없을 때 쓸 값 (명세 servers[0].url)
    timeout_ms: int = 5000
    auth_type: AuthType = "NONE"
    auth_profile: str | None = None             # 비밀값 참조 이름
    auth_headers: list[str] = Field(default_factory=list)   # 헤더 이름 — 값은 비밀값 저장소에서 주입
    default_headers: dict[str, str] = Field(default_factory=dict)
    allowed_environments: list[str] = Field(default_factory=lambda: ["DEV"])
    source: str = "default"                     # 값이 어디서 왔는지 — domain / service / spec


class ToolSpec(BaseModel):
    """API 하나 = 도구 하나. PK 는 api_id."""

    api_id: str
    domain: str
    method: str
    endpoint: str                               # 서버 주소를 뺀 경로
    content_type: str | None = None
    body_format: str | None = None              # nexacro-xml · json …
    base_url: str                               # 환경변수 이름
    timeout_ms: int
    retry_count: int                            # 고정 규칙: 쓰기 0 · 조회 2
    approval_required: bool                     # 고정 규칙: 쓰기 True
    auth_type: AuthType
    auth_profile: str | None = None
    enabled: bool = True                        # tool_enabled 의 원본
    default_headers: dict[str, str] = Field(default_factory=dict)
    success_rule: dict[str, str] | None = None  # {path, equals} — 성공 · 실패 모두 HTTP 200 이라 본문으로 판단
    allowed_environments: list[str] = Field(default_factory=lambda: ["DEV"])
    schema_ref: str | None = None               # 1차 비움 — 2차에 Canonical Schema 참조
    source_metadata: dict[str, str | None] = Field(default_factory=dict)   # document_id · operation_id · spec_hash
